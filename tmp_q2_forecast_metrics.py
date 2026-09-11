import importlib.util, numpy as np
p=r'D:\AAA数模\参赛材料\第二问\solve_q2.py'
spec=importlib.util.spec_from_file_location('q2',p); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
ld,pv,pr=m.read_data(); dates=list(ld.date); a=ld.iloc[:,1:].to_numpy(float); b=pv.iloc[:,1:].to_numpy(float); si=dates.index(__import__('datetime').date(2025,2,1)); lp,vp=m.build_predictions(a,b,dates,si)
for name,y,yh in [('load',a,lp),('pv',b,vp)]:
 e=(yh[si:]-y[si:]).ravel(); print(name,'MAE',np.mean(np.abs(e)),'RMSE',np.sqrt(np.mean(e*e)),'Bias',np.mean(e),'P90AE',np.quantile(np.abs(e),.9))
for name,y,yh in [('load',a,lp),('pv',b,vp)]:
 print(name,'monthly')
 for mon in range(2,13):
  ids=[i for i,d in enumerate(dates) if d.month==mon]; e=(yh[ids]-y[ids]).ravel(); print(mon,round(np.mean(np.abs(e)),2),round(np.sqrt(np.mean(e*e)),2),round(np.mean(e),2))
