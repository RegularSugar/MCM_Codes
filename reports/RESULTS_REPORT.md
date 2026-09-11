# 第一问计算结果

## 运行环境

- 求解语言：Python 3.14
- 优化器：PuLP 3.3.2，CBC MILP solver
- 输入：`CUMCM2026Problems/C题/附件/附件1.xlsx`
- 输出目录：`code/outputs/`

## 优化结果

| 指标 | 数值 |
| --- | ---: |
| 无储能基准购电量 | 61789.9354 kWh |
| 无储能基准购电费 | 48052.0466 元 |
| 储能优化购电量 | 59482.6992 kWh |
| 储能优化购电费 | 35126.9487 元 |
| 购电费节约 | 12925.0979 元 |
| 费用降幅 | 26.9% |
| 光伏弃光量 | 0.0000 kWh |
| 充电量（交流侧累计） | 20740.6661 kWh |
| 放电量（交流侧累计） | 16799.9396 kWh |
| 初始/末端储电量 | 6000.0000 / 6000.0000 kWh |

费用降幅按 `(48052.0466-35126.9487)/48052.0466` 计算。优化后的购电量不一定按相同比例下降，因为充放电效率造成储能损耗，优化目标是费用而非购电量。

## 分时储能汇总

| 时段 | 充电量 kWh | 放电量 kWh |
| --- | ---: | ---: |
| 0:00-4:00 | 4500.0000 | 0.0000 |
| 4:00-8:00 | 833.3333 | 6365.8412 |
| 8:00-12:00 | 4787.9643 | 1702.9970 |
| 12:00-16:00 | 5286.0352 | 91.1014 |
| 16:00-20:00 | 0.0000 | 5780.1319 |
| 20:00-24:00 | 5333.3333 | 2859.8681 |

指定时段的单个十分钟购电量：10:00为0.0000 kWh，12:00为480.4125 kWh，14:00为0.0000 kWh，16:00为445.4317 kWh，18:00为531.8941 kWh，20:00为0.0000 kWh。

当前结果与复现仓库的 HiGHS 结果对照：参考费用为35126.948589元、购电量为59482.698998 kWh。CBC结果与其费用相差约`8.6e-05`元、购电量相差约`3.0e-04`kWh，处于求解器容差和退化最优解的数值误差范围；逐段购电量和六段汇总最大差异不超过`1e-4 kWh`。

## 约束校验

`code/outputs/q1_validation.csv` 给出独立重算的校验结果：

- 最大母线平衡残差：`5.33e-05 kWh`
- 最大SOC递推残差：`4.73e-04 kWh`
- SOC范围：`1200.0000--10800.0000 kWh`
- 最大单段充电量：`833.33333 kWh`，对应5000 kW功率上限
- 最大单段放电量：`715.65303 kWh`，低于功率上限
- 同时充放电时段：`0`
- 末端SOC误差：`0`

残差来自CBC求解器有限小数容差，远低于输入数据精度；代码以 `1e-3 kWh` 阈值执行校验。

## 文件与复现

- 逐十分钟内部调度：[q1_schedule_internal.csv](../code/outputs/q1_schedule_internal.csv)
- 按模板顺序购电量：[q1_schedule_template_order.csv](../code/outputs/q1_schedule_template_order.csv)
- 六个四小时充放电汇总：[q1_battery_summary.csv](../code/outputs/q1_battery_summary.csv)
- 核心指标：[q1_key_results.csv](../code/outputs/q1_key_results.csv)
- 约束校验：[q1_validation.csv](../code/outputs/q1_validation.csv)
- 官方原模板格式结果：[result1_第一问.xlsx](../outputs/first_question/result1_第一问.xlsx)。该文件保留模板原有时段文字，仅填入数值；论文表格中的物理时段仍按附件标签为右端点解释。

Python求解及结果表写入命令：

```powershell
& 'C:\Users\HongsenWang\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' D:\AAA数模\code\solve_q1_milp.py
& 'C:\Users\HongsenWang\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe' D:\AAA数模\code\build_result1_workbook.mjs
```
