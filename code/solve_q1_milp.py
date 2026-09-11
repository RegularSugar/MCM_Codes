"""C题问题一：纯 Python 的典型日储能经济调度（MILP）。

本程序沿用资料目录“整数规划模型/integer_programming.py”的 PuLP 建模结构，
并扩展为144个十分钟段的储能混合整数线性规划。它不使用 MATLAB。

运行：
  C:/Users/HongsenWang/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe code/solve_q1_milp.py
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

def locate_project_dir() -> Path:
    """Locate the project root whether this script is run from code/ or source/."""
    script_dir = Path(__file__).resolve().parent
    for candidate in (script_dir, *script_dir.parents):
        if (candidate / "CUMCM2026Problems" / "C题" / "附件" / "附件1.xlsx").is_file():
            return candidate
    raise FileNotFoundError("未找到 CUMCM2026Problems/C题/附件/附件1.xlsx。")


def locate_output_dir(project_dir: Path) -> Path:
    """Write beside the support-material source folder when copied there."""
    script_dir = Path(__file__).resolve().parent
    if script_dir.name == "source" and script_dir.parent.name == "第一问":
        return script_dir.parent / "outputs"
    return project_dir / "code" / "outputs"


PROJECT_DIR = locate_project_dir()
# PuLP 固定安装在项目内，不要求修改系统 Python 环境。
vendor_dir = PROJECT_DIR / "code" / "vendor"
if vendor_dir.is_dir():
    sys.path.insert(0, str(vendor_dir))

import pandas as pd
import pulp as pl


DT_HOUR = 1 / 6
ETA_CHARGE = 0.90
ETA_DISCHARGE = 0.90
SOC_INITIAL = 6000.0
SOC_MIN = 1200.0
SOC_MAX = 10800.0
PERIOD_LIMIT = 5000.0 * DT_HOUR  # 833.3333 kWh per 10 min
# CBC 以有限小数写回变量；1e-3 kWh远小于输入的0.0001 kW精度及10分钟转换误差。
TOL = 1e-3


def interval_label(start_minute: int) -> str:
    """Return a 10-minute interval label in internal same-day calendar order."""
    end_minute = start_minute + 10
    return (
        f"{start_minute // 60:02d}:{start_minute % 60:02d}-"
        f"{end_minute // 60:02d}:{end_minute % 60:02d}"
    )


def write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def clean(value: float) -> float:
    """Only remove solver-scale numerical noise; never round valid schedules."""
    return 0.0 if abs(value) < 1e-7 else float(value)


def main() -> None:
    input_path = PROJECT_DIR / "CUMCM2026Problems" / "C题" / "附件" / "附件1.xlsx"
    output_dir = locate_output_dir(PROJECT_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)

    raw = pd.read_excel(input_path)
    if len(raw) != 144 or raw.shape[1] < 4:
        raise ValueError("附件1必须包含144行及时间、电价、负载、光伏预测四列。")

    # 参考仓库口径：附件标签是区间右端点。原始首行0:10对应00:00--00:10，
    # 末行0:00+1对应23:50--24:00，因此不循环移动数据。
    internal = raw.reset_index(drop=True)
    price = internal.iloc[:, 1].astype(float).tolist()
    load_kwh = (internal.iloc[:, 2].astype(float) * DT_HOUR).tolist()
    pv_kwh = (internal.iloc[:, 3].astype(float) * DT_HOUR).tolist()
    periods = list(range(144))

    # 与参考整数规划代码相同：定义问题、变量、目标、约束、求解与结果输出。
    model = pl.LpProblem("Q1_Typical_Day_Storage_Dispatch", pl.LpMinimize)
    grid = pl.LpVariable.dicts("grid_purchase_kWh", periods, lowBound=0)
    charge = pl.LpVariable.dicts("charge_kWh", periods, lowBound=0, upBound=PERIOD_LIMIT)
    discharge = pl.LpVariable.dicts("discharge_kWh", periods, lowBound=0, upBound=PERIOD_LIMIT)
    curtail = pl.LpVariable.dicts("curtailment_kWh", periods, lowBound=0)
    soc = pl.LpVariable.dicts("end_SOC_kWh", periods, lowBound=SOC_MIN, upBound=SOC_MAX)
    is_charging = pl.LpVariable.dicts("is_charging", periods, cat=pl.LpBinary)

    model += pl.lpSum(price[t] * grid[t] for t in periods), "daily_grid_cost_yuan"
    for t in periods:
        # 母线能量平衡：购电 + 光伏 - 弃光 + 放电 = 负荷 + 充电。
        model += (
            grid[t] + pv_kwh[t] - curtail[t] + discharge[t]
            == load_kwh[t] + charge[t]
        ), f"energy_balance_{t:03d}"
        # SOC递推；C、D均为交流母线侧电量。
        previous_soc = SOC_INITIAL if t == 0 else soc[t - 1]
        model += (
            soc[t] == previous_soc + ETA_CHARGE * charge[t] - discharge[t] / ETA_DISCHARGE
        ), f"soc_transition_{t:03d}"
        # 充放电互斥。
        model += charge[t] <= PERIOD_LIMIT * is_charging[t], f"charge_mutex_{t:03d}"
        model += discharge[t] <= PERIOD_LIMIT * (1 - is_charging[t]), f"discharge_mutex_{t:03d}"
    model += soc[143] == SOC_INITIAL, "cyclic_terminal_SOC"

    solver = pl.PULP_CBC_CMD(msg=False, gapRel=1e-9)
    status = model.solve(solver)
    if pl.LpStatus[status] != "Optimal":
        raise RuntimeError(f"MILP未得到最优解，状态为：{pl.LpStatus[status]}")

    g = [clean(pl.value(grid[t])) for t in periods]
    c = [clean(pl.value(charge[t])) for t in periods]
    d = [clean(pl.value(discharge[t])) for t in periods]
    w = [clean(pl.value(curtail[t])) for t in periods]
    s = [clean(pl.value(soc[t])) for t in periods]
    z = [int(round(pl.value(is_charging[t]))) for t in periods]

    balance = [g[t] + pv_kwh[t] - w[t] + d[t] - load_kwh[t] - c[t] for t in periods]
    state = []
    prior_soc = SOC_INITIAL
    for t in periods:
        state.append(s[t] - prior_soc - ETA_CHARGE * c[t] + d[t] / ETA_DISCHARGE)
        prior_soc = s[t]
    simultaneous = sum(c[t] > TOL and d[t] > TOL for t in periods)
    validation = {
        "max_balance_residual_kWh": max(abs(x) for x in balance),
        "max_state_residual_kWh": max(abs(x) for x in state),
        "min_SOC_kWh": min(s),
        "max_SOC_kWh": max(s),
        "max_charge_kWh": max(c),
        "max_discharge_kWh": max(d),
        "simultaneous_charge_discharge_periods": simultaneous,
        "terminal_SOC_error_kWh": abs(s[-1] - SOC_INITIAL),
    }
    if (
        validation["max_balance_residual_kWh"] > TOL
        or validation["max_state_residual_kWh"] > TOL
        or simultaneous != 0
        or validation["terminal_SOC_error_kWh"] > TOL
    ):
        raise RuntimeError(f"求解结果未通过物理约束校验：{validation}")

    schedule_rows = []
    for t in periods:
        schedule_rows.append({
            "internal_period": t + 1,
            "time_interval": interval_label(t * 10),
            "price_yuan_per_kWh": price[t],
            "load_kWh": load_kwh[t],
            "pv_kWh": pv_kwh[t],
            "grid_purchase_kWh": g[t],
            "charge_kWh": c[t],
            "discharge_kWh": d[t],
            "curtailment_kWh": w[t],
            "end_SOC_kWh": s[t],
            "charge_indicator": z[t],
        })
    write_csv(output_dir / "q1_schedule_internal.csv", list(schedule_rows[0]), schedule_rows)

    # 数值按原始附件序列写出；result1.xlsx 保持官方模板给出的时间标签不变。
    template_purchase = g
    template_rows = [{"grid_purchase_kWh": value} for value in template_purchase]
    write_csv(output_dir / "q1_schedule_template_order.csv", ["grid_purchase_kWh"], template_rows)

    battery_rows = []
    for block in range(6):
        indices = range(24 * block, 24 * (block + 1))
        battery_rows.append({
            "interval_start_hour": 4 * block,
            "charge_kWh": sum(c[t] for t in indices),
            "discharge_kWh": sum(d[t] for t in indices),
        })
    write_csv(output_dir / "q1_battery_summary.csv", list(battery_rows[0]), battery_rows)

    selected_rows = [
        {"interval_start_hour": hour, "grid_purchase_kWh": g[hour * 6]}
        for hour in (10, 12, 14, 16, 18, 20)
    ]
    write_csv(output_dir / "q1_specified_intervals.csv", list(selected_rows[0]), selected_rows)

    baseline_g = [max(load_kwh[t] - pv_kwh[t], 0.0) for t in periods]
    key_results = {
        "optimized_grid_purchase_kWh": sum(g),
        "optimized_grid_cost_yuan": pl.value(model.objective),
        "baseline_grid_purchase_kWh": sum(baseline_g),
        "baseline_grid_cost_yuan": sum(price[t] * baseline_g[t] for t in periods),
        "cost_saving_yuan": sum(price[t] * baseline_g[t] for t in periods) - pl.value(model.objective),
        "curtailment_kWh": sum(w),
        "charge_throughput_kWh": sum(c),
        "discharge_throughput_kWh": sum(d),
        "load_energy_kWh": sum(load_kwh),
        "pv_energy_kWh": sum(pv_kwh),
        "SOC_0000_kWh": SOC_INITIAL,
        "SOC_2400_kWh": s[-1],
    }
    write_csv(output_dir / "q1_key_results.csv", list(key_results), [key_results])
    write_csv(output_dir / "q1_validation.csv", list(validation), [validation])

    print(f"Solver status: {pl.LpStatus[status]}")
    print(f"Optimal daily grid cost: {pl.value(model.objective):.6f} yuan")
    print(f"Optimized grid energy: {sum(g):.6f} kWh")
    print(f"Saved result CSV files to: {output_dir}")


if __name__ == "__main__":
    main()
