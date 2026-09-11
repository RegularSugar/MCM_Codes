# -*- coding: utf-8 -*-
"""C题问题2改进版：历史滚动预测 + 净负荷分位数 + 48小时滚动MILP。

核心原则：
1. 日期d的计划只使用d日0:00以前的附件2数据；
2. 负荷用最近4个同星期几预测，光伏用最近7日同时间均值预测；
3. 对净负荷误差而非负荷/PV误差分别加裕度；
4. 优化未来48小时，但仅执行前24小时，第二天重新预测与优化；
5. 用当天真实数据事后回放，缺口按5倍价格紧急购电。
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[3]
ATT = ROOT / "CUMCM2026Problems" / "C题" / "附件"
OUT = Path(__file__).resolve().parent.parent / "outputs1"
OUT.mkdir(parents=True, exist_ok=True)
VENDOR = ROOT / "code" / "vendor"
if VENDOR.is_dir():
    sys.path.insert(0, str(VENDOR))
import pulp as pl

DT = 1 / 6
N = 144
ETA_C = ETA_D = 0.90
S_MIN, S_MAX, S_INITIAL = 1200.0, 10800.0, 6000.0
M = 5000 * DT
ERROR_WINDOW = 56
EPS_THROUGHPUT = 1e-7
TOL = 1e-3


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--risk-q", type=float, default=0.80)
    p.add_argument("--horizon-days", type=int, choices=(1, 2), default=2)
    p.add_argument("--tag", default="improved")
    p.add_argument("--no-workbook", action="store_true")
    p.add_argument("--output-dir", default=None,
                   help="结果输出目录，默认使用脚本目录下的 outputs")
    return p.parse_args()


def read_inputs():
    x1 = pd.read_excel(ATT / "附件1.xlsx")
    price = x1.iloc[:, 1].astype(float).to_numpy()
    seed_load = x1.iloc[:, 2].astype(float).to_numpy()
    seed_pv = x1.iloc[:, 3].astype(float).to_numpy()
    a2 = pd.ExcelFile(ATT / "附件2.xlsx")
    load_raw = pd.read_excel(ATT / "附件2.xlsx", sheet_name=a2.sheet_names[0])
    pv_raw = pd.read_excel(ATT / "附件2.xlsx", sheet_name=a2.sheet_names[1])

    def unpack(frame):
        raw = frame.iloc[:, 0]
        if pd.api.types.is_numeric_dtype(raw):
            dates = list(pd.to_datetime(raw, unit="D", origin="1899-12-30").dt.date)
        else:
            dates = list(pd.to_datetime(raw).dt.date)
        values = frame.iloc[:, 1:145].astype(float).to_numpy()
        return dates, values

    dates_l, load = unpack(load_raw)
    dates_p, pv = unpack(pv_raw)
    if dates_l != dates_p or len(dates_l) != 365 or load.shape != (365, N):
        raise ValueError("附件2日期或144点数据结构不正确")
    if np.any(~np.isfinite(load)) or np.any(~np.isfinite(pv)) or np.any(load < 0) or np.any(pv < 0):
        raise ValueError("附件2存在缺失、无穷或负功率")
    return dates_l, load, pv, price, seed_load, seed_pv


def forecast_asof(hist, dates, issue_idx, target_date, kind, seed):
    """在issue_idx日0:00，只用下标小于issue_idx的数据预测target_date。"""
    eligible = list(range(issue_idx))
    if not eligible:
        return seed.copy()
    if kind == "load":
        chosen = [i for i in eligible if dates[i].weekday() == target_date.weekday()][-4:]
        if not chosen:
            chosen = eligible[-min(7, len(eligible)):]
        return np.mean(hist[chosen], axis=0)
    chosen = eligible[-min(7, len(eligible)):]
    return np.mean(hist[chosen], axis=0)


def precompute_one_day_predictions(dates, load, pv, seed_load, seed_pv):
    lp = np.zeros_like(load, dtype=float)
    vp = np.zeros_like(pv, dtype=float)
    for i, d in enumerate(dates):
        lp[i] = forecast_asof(load, dates, i, d, "load", seed_load)
        vp[i] = forecast_asof(pv, dates, i, d, "pv", seed_pv)
    return lp, vp


def net_margin(issue_idx, actual_net, predicted_net, risk_q):
    valid = np.arange(max(0, issue_idx - ERROR_WINDOW), issue_idx)
    if len(valid) < 7:
        return np.zeros(N)
    errors = actual_net[valid] - predicted_net[valid]
    margin = np.quantile(errors, risk_q, axis=0)
    # 三点中位数抑制单个十分钟格的偶然尖峰，不跨日期使用未来信息。
    padded = np.pad(margin, (1, 1), mode="edge")
    return np.median(np.vstack([padded[:-2], padded[1:-1], padded[2:]]), axis=0)


def build_horizon_net(issue_idx, horizon_days, dates, load, pv, lp, vp,
                      seed_load, seed_pv, risk_q):
    actual_net = load - pv
    predicted_net = lp - vp
    margin = net_margin(issue_idx, actual_net, predicted_net, risk_q)
    curves = []
    issue_date = dates[issue_idx]
    for k in range(horizon_days):
        target = issue_date + timedelta(days=k)
        if k == 0:
            lhat, vhat = lp[issue_idx], vp[issue_idx]
        else:
            lhat = forecast_asof(load, dates, issue_idx, target, "load", seed_load)
            vhat = forecast_asof(pv, dates, issue_idx, target, "pv", seed_pv)
        curves.append(lhat - vhat + margin)
    return np.concatenate(curves), margin


def solve_horizon(net_kw, price_day, s0, horizon_days):
    h = N * horizon_days
    net_e = net_kw * DT
    price = np.tile(price_day, horizon_days)
    model = pl.LpProblem("Q2_rolling_horizon", pl.LpMinimize)
    g = pl.LpVariable.dicts("grid", range(h), lowBound=0)
    c = pl.LpVariable.dicts("charge", range(h), lowBound=0, upBound=M)
    d = pl.LpVariable.dicts("discharge", range(h), lowBound=0, upBound=M)
    w = pl.LpVariable.dicts("surplus_curtail", range(h), lowBound=0)
    s = pl.LpVariable.dicts("soc", range(h), lowBound=S_MIN, upBound=S_MAX)
    z = pl.LpVariable.dicts("charge_mode", range(h), cat=pl.LpBinary)
    model += pl.lpSum(float(price[t]) * g[t] + EPS_THROUGHPUT * (c[t] + d[t]) for t in range(h))
    for t in range(h):
        prev = float(s0) if t == 0 else s[t - 1]
        # G + D - C - W = 风险调整后的净负荷(L-PV)
        model += g[t] + d[t] - c[t] - w[t] == float(net_e[t])
        model += s[t] == prev + ETA_C * c[t] - d[t] / ETA_D
        model += c[t] <= M * z[t]
        model += d[t] <= M * (1 - z[t])
    # 仅在48小时远端回到当前SOC，消除日末任意惩罚；第一天末SOC可自由变化。
    model += s[h - 1] == float(s0)
    solver = pl.PULP_CBC_CMD(msg=False, gapRel=1e-8)
    tic = time.perf_counter()
    status = model.solve(solver)
    elapsed = time.perf_counter() - tic
    if pl.LpStatus[status] != "Optimal":
        raise RuntimeError(f"滚动MILP失败: {pl.LpStatus[status]}")
    take = slice(0, N)
    full = {
        "g": np.array([max(0.0, pl.value(g[t])) for t in range(h)]),
        "c": np.array([max(0.0, pl.value(c[t])) for t in range(h)]),
        "d": np.array([max(0.0, pl.value(d[t])) for t in range(h)]),
        "w": np.array([max(0.0, pl.value(w[t])) for t in range(h)]),
        "s": np.array([pl.value(s[t]) for t in range(h)]),
    }
    return {k: v[take].copy() for k, v in full.items()}, elapsed


def intervals(values):
    out, t = [], 0
    while t < N:
        if values[t] <= TOL:
            t += 1
            continue
        start, total = t, 0.0
        while t < N and values[t] > TOL:
            total += float(values[t]); t += 1
        out.append((start, t, total))
    return out


def time_text(start, end):
    def f(k):
        if k == N: return "24:00"
        return f"{k*10//60:02d}:{k*10%60:02d}"
    return f"{f(start)}-{f(end)}"


def write_workbook(days, plans, emergency_rows):
    src = ATT / "附件5" / "result2.xlsx"
    dst = OUT / "result2.xlsx"
    shutil.copy2(src, dst)
    wb = load_workbook(dst)
    plan_ws, batt_ws, emerg_ws = wb.worksheets[:3]
    for r, day in enumerate(days, 2):
        plan_ws.cell(r, 1, pd.Timestamp(day).to_pydatetime())
        for t, value in enumerate(plans[day]["g"], 2):
            plan_ws.cell(r, t, round(float(value), 4)).number_format = "0.0000"
    labels = ["0:00-4:00", "4:00-8:00", "8:00-12:00",
              "12:00-16:00", "16:00-20:00", "20:00-24:00"]
    for di, day in enumerate(days):
        for b in range(6):
            r = 2 + 6 * di + b; sl = slice(24*b, 24*(b+1))
            batt_ws.cell(r, 1, pd.Timestamp(day).to_pydatetime() if b == 0 else None)
            batt_ws.cell(r, 2, labels[b])
            batt_ws.cell(r, 3, round(float(plans[day]["c"][sl].sum()), 4)).number_format = "0.0000"
            batt_ws.cell(r, 4, round(float(plans[day]["d"][sl].sum()), 4)).number_format = "0.0000"
            batt_ws.cell(r, 5, "0:00" if b == 0 else ("24:00" if b == 1 else None))
            batt_ws.cell(r, 6, round(float(plans[day]["s0"] if b == 0 else plans[day]["s"][-1]), 4) if b < 2 else None).number_format = "0.0000"
    while emerg_ws.max_row > 1:
        emerg_ws.delete_rows(2)
    for r, row in enumerate(emergency_rows, 2):
        emerg_ws.cell(r, 1, pd.Timestamp(row["date"]).to_pydatetime())
        emerg_ws.cell(r, 2, row["interval"])
        emerg_ws.cell(r, 3, round(row["energy_kWh"], 4)).number_format = "0.0000"
    wb.save(dst)
    return dst


def main():
    args = parse_args()
    if not 0.5 < args.risk_q < 1:
        raise ValueError("risk-q必须在0.5与1之间")
    global OUT
    if args.output_dir:
        OUT = Path(args.output_dir).resolve()
        OUT.mkdir(parents=True, exist_ok=True)
    dates, load, pv, price, seed_load, seed_pv = read_inputs()
    lp, vp = precompute_one_day_predictions(dates, load, pv, seed_load, seed_pv)
    start = dates.index(date(2025, 2, 1))
    old_summary = None
    old_file = OUT / "q2_validation.csv"
    if old_file.exists():
        old_summary = pd.read_csv(old_file).iloc[0].to_dict()

    plans, daily, emergency_rows, checks = {}, [], [], []
    s0 = S_INITIAL
    total_solve_time = 0.0
    for i, day in enumerate(dates):
        net_risk_kw, margin = build_horizon_net(
            i, args.horizon_days, dates, load, pv, lp, vp,
            seed_load, seed_pv, args.risk_q
        )
        sol, elapsed = solve_horizon(net_risk_kw, price, s0, args.horizon_days)
        total_solve_time += elapsed
        actual_net_e = (load[i] - pv[i]) * DT
        gap = actual_net_e + sol["c"] - sol["d"] - sol["g"]
        emergency = np.maximum(gap, 0.0)
        surplus = np.maximum(-gap, 0.0)
        expected_soc = s0 + np.cumsum(ETA_C * sol["c"] - sol["d"] / ETA_D)
        risk_net_e = net_risk_kw[:N] * DT
        plan_balance = sol["g"] + sol["d"] - sol["c"] - sol["w"] - risk_net_e
        actual_balance = sol["g"] + sol["d"] + emergency - sol["c"] - surplus - actual_net_e
        soc_residual = sol["s"] - expected_soc
        next_s0 = float(sol["s"][-1])
        if i >= start:
            for a, b, amount in intervals(emergency):
                emergency_rows.append({"date": day, "interval": time_text(a, b), "energy_kWh": amount})
            plan_cost = float(price @ sol["g"])
            emergency_cost = float(5 * price @ emergency)
            plans[day] = {**sol, "s0": s0, "emergency": emergency, "surplus": surplus}
            daily.append({
                "date": day.isoformat(), "soc_start_kWh": s0, "soc_end_kWh": next_s0,
                "plan_cost_yuan": plan_cost, "emergency_cost_yuan": emergency_cost,
                "total_cost_yuan": plan_cost + emergency_cost,
                "planned_grid_kWh": float(sol["g"].sum()),
                "emergency_grid_kWh": float(emergency.sum()),
                "emergency_intervals": len(intervals(emergency)),
                "charge_kWh": float(sol["c"].sum()), "discharge_kWh": float(sol["d"].sum()),
                "surplus_kWh": float(surplus.sum()), "solve_time_s": elapsed,
            })
            checks.append({
                "date": day.isoformat(),
                "max_plan_balance_residual_kWh": float(np.max(np.abs(plan_balance))),
                "max_actual_balance_residual_kWh": float(np.max(np.abs(actual_balance))),
                "max_soc_residual_kWh": float(np.max(np.abs(soc_residual))),
                "min_soc_kWh": float(sol["s"].min()), "max_soc_kWh": float(sol["s"].max()),
                "max_charge_kWh": float(sol["c"].max()), "max_discharge_kWh": float(sol["d"].max()),
                "simultaneous_periods": int(np.sum((sol["c"] > TOL) & (sol["d"] > TOL))),
            })
        s0 = next_s0

    daily_df = pd.DataFrame(daily); check_df = pd.DataFrame(checks)
    valid_slice = slice(start, None)
    pred_rows = []
    for name, actual, pred in (("load", load, lp), ("pv", pv, vp), ("net_load", load-pv, lp-vp)):
        e = (pred[valid_slice] - actual[valid_slice]).ravel()
        pred_rows.append({"variable": name, "MAE_kW": float(np.mean(np.abs(e))),
                          "RMSE_kW": float(np.sqrt(np.mean(e*e))), "Bias_kW": float(np.mean(e)),
                          "P90_absolute_error_kW": float(np.quantile(np.abs(e), .9))})
    summary = {
        "method": "net-load quantile + rolling horizon MILP", "risk_q": args.risk_q,
        "horizon_days": args.horizon_days, "days": len(daily_df),
        "plan_cost_yuan": float(daily_df.plan_cost_yuan.sum()),
        "emergency_cost_yuan": float(daily_df.emergency_cost_yuan.sum()),
        "total_cost_yuan": float(daily_df.total_cost_yuan.sum()),
        "planned_grid_kWh": float(daily_df.planned_grid_kWh.sum()),
        "emergency_grid_kWh": float(daily_df.emergency_grid_kWh.sum()),
        "emergency_days": int((daily_df.emergency_grid_kWh > TOL).sum()),
        "emergency_intervals": int(daily_df.emergency_intervals.sum()),
        "min_soc_kWh": float(check_df.min_soc_kWh.min()), "max_soc_kWh": float(check_df.max_soc_kWh.max()),
        "max_plan_balance_residual_kWh": float(check_df.max_plan_balance_residual_kWh.max()),
        "max_actual_balance_residual_kWh": float(check_df.max_actual_balance_residual_kWh.max()),
        "max_soc_residual_kWh": float(check_df.max_soc_residual_kWh.max()),
        "simultaneous_periods": int(check_df.simultaneous_periods.sum()),
        "total_solve_time_s": total_solve_time,
    }
    tag = args.tag
    daily_df.to_csv(OUT / f"q2_{tag}_daily_summary.csv", index=False, encoding="utf-8-sig")
    check_df.to_csv(OUT / f"q2_{tag}_validation_detail.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(pred_rows).to_csv(OUT / f"q2_{tag}_forecast_accuracy.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(emergency_rows).to_csv(OUT / f"q2_{tag}_emergency_intervals.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame([summary]).to_csv(OUT / f"q2_{tag}_summary.csv", index=False, encoding="utf-8-sig")
    (OUT / f"q2_{tag}_summary.json").write_text(json.dumps({"new": summary, "old": old_summary}, ensure_ascii=False, indent=2), encoding="utf-8")
    result = None
    if not args.no_workbook:
        result = write_workbook(dates[start:], plans, emergency_rows)
    print(json.dumps({"result": str(result) if result else None, **summary}, ensure_ascii=False))


if __name__ == "__main__":
    main()
