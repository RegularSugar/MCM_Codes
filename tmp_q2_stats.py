import pandas as pd
base=r'D:\AAA数模\参赛材料\第二问\outputs'
d=pd.read_csv(base+r'\q2_daily_summary.csv')
e=pd.read_csv(base+r'\q2_emergency_intervals.csv')
print('TOTALS')
for c in ['plan_cost_yuan','emergency_cost_yuan','total_cost_yuan','planned_grid_kWh','emergency_grid_kWh','charge_kWh','discharge_kWh','curtailment_kWh']:
 print(c, d[c].sum())
print('emergency ratio',d.emergency_grid_kWh.sum()/(d.planned_grid_kWh.sum()+d.emergency_grid_kWh.sum()))
print('daily cost mean',d.total_cost_yuan.mean(),'p95',d.total_cost_yuan.quantile(.95))
for x in ['2025-03-20','2025-06-21','2025-09-23','2025-12-21']:
 print('\nDATE',x)
 print(d[d.date==x].to_string(index=False))
 print(e[e.date==x].to_string(index=False))
