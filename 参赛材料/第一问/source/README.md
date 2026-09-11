# C题第一问支撑材料

`solve_q1_milp.py` 为问题一的 Python 混合整数线性规划求解程序，读取附件 1 并输出 144 个十分钟时段的购电、充放电、SOC 和校验结果。

`build_result1_workbook.py` 将求解得到的 CSV 写入附件 5 的 `result1.xlsx` 模板。脚本保留官方模板的工作表、布局和全部时间标签，只填写数值单元格。

运行顺序：先执行 `solve_q1_milp.py`，再执行 `build_result1_workbook.py`。程序会自动向上定位 `CUMCM2026Problems/C题/附件/附件1.xlsx`，并在本目录同级的 `outputs` 文件夹生成结果。

Python 依赖见 `requirements.txt`。
