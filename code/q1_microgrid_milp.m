%% C题第一问：典型日微电网经济调度（MILP）
% 输入：CUMCM2026Problems/C题/附件/附件1.xlsx
% 输出：outputs/q1/result1.xlsx（按题目给出的模板顺序填写）
%
% 本程序按 `C题第一问_口径与对话交接.md` 的约定处理时间：
% 附件中最后一行“0:00+1”视为 00:00--00:10，并移到典型日的首行。
% 变量均为一个十分钟时段内的能量（kWh），因此功率数据须乘 dt=1/6 h。

clear; clc;

%% 1. 参数与数据
thisFile = mfilename('fullpath');
projectRoot = fileparts(fileparts(thisFile));
inputFile = fullfile(projectRoot, 'CUMCM2026Problems', 'C题', '附件', '附件1.xlsx');
templateFile = fullfile(projectRoot, 'CUMCM2026Problems', 'C题', '附件', '附件5', 'result1.xlsx');
outDir = fullfile(projectRoot, 'outputs', 'q1');
if ~exist(outDir, 'dir'); mkdir(outDir); end
outFile = fullfile(outDir, 'result1.xlsx');

dt = 1/6;             % h，单个时段长度
eta_c = 0.90;         % 充电效率：交流侧充入 1 kWh，电池增加 0.9 kWh
eta_d = 0.90;         % 放电效率：电池减少 1/0.9 kWh，交流侧输出 1 kWh
E0 = 6000;            % kWh，0:00 初始储能
Emin = 1200; Emax = 10800;
Pmax = 5000;          % kW
M = Pmax * dt;        % 每时段交流侧最大充/放电量，kWh

raw = readtable(inputFile, 'VariableNamingRule', 'preserve');
n = height(raw);
assert(n == 144, '附件1应有144个十分钟时段。');
priceRaw = raw{:, 2};
loadRaw = raw{:, 3} * dt;
pvRaw = raw{:, 4} * dt;
assert(all(priceRaw >= 0) && all(loadRaw >= 0) && all(pvRaw >= 0), ...
    '电价、负荷和光伏数据必须非负。');

% 典型日内部顺序：00:00--00:10, 00:10--00:20, ..., 23:50--24:00
order = [n, 1:n-1];
price = priceRaw(order);
L = loadRaw(order);
PV = pvRaw(order);

%% 2. MILP：x=[G(1:n), C(1:n), D(1:n), W(1:n), E(1:n), y(1:n)]'
% G: 外网购电；C: 交流母线侧充电输入；D: 交流母线侧放电输出；
% W: 弃光；E: 每个时段结束时的电池储能；y: 充电状态(1=充电, 0=放电)。
ng = n; nc = n; nd = n; nw = n; ne = n; ny = n;
iG = 1:ng;
iC = ng + (1:nc);
iD = ng + nc + (1:nd);
iW = ng + nc + nd + (1:nw);
iE = ng + nc + nd + nw + (1:ne);
iY = ng + nc + nd + nw + ne + (1:ny);
N = 6*n;

f = zeros(N, 1); f(iG) = price;
intcon = iY;
lb = zeros(N, 1); ub = inf(N, 1);
ub(iW) = PV;
lb(iE) = Emin; ub(iE) = Emax;
ub(iY) = 1;

% 能量平衡：G_t + D_t + PV_t - W_t = L_t + C_t
Aeq = zeros(2*n + 1, N); beq = zeros(2*n + 1, 1);
for t = 1:n
    Aeq(t, iG(t)) = 1; Aeq(t, iD(t)) = 1;
    Aeq(t, iW(t)) = -1; Aeq(t, iC(t)) = -1;
    beq(t) = L(t) - PV(t);
end

% 状态方程：E_t = E_(t-1) + eta_c*C_t - D_t/eta_d
for t = 1:n
    r = n + t;
    Aeq(r, iE(t)) = 1;
    Aeq(r, iC(t)) = -eta_c;
    Aeq(r, iD(t)) = 1/eta_d;
    if t == 1
        beq(r) = E0;
    else
        Aeq(r, iE(t-1)) = -1;
    end
end
% 周期性：24:00 储能恢复至 0:00 的 6000 kWh
Aeq(2*n+1, iE(n)) = 1; beq(2*n+1) = E0;

% 充/放电互斥及功率上限：C_t <= M*y_t, D_t <= M*(1-y_t)
A = zeros(2*n, N); b = zeros(2*n, 1);
for t = 1:n
    A(t, iC(t)) = 1; A(t, iY(t)) = -M;
    A(n+t, iD(t)) = 1; A(n+t, iY(t)) = M; b(n+t) = M;
end

opts = optimoptions('intlinprog', 'Display', 'off', 'RelativeGapTolerance', 1e-9);
[x, totalCost, exitflag, output] = intlinprog(f, intcon, A, b, Aeq, beq, lb, ub, opts);
assert(exitflag > 0, 'MILP未求得可行最优解：%s', output.message);

G = x(iG); C = x(iC); D = x(iD); W = x(iW); E = x(iE);

%% 3. 独立约束核验
balanceResidual = G + D + PV - W - L - C;
stateResidual = [E(1) - E0 - eta_c*C(1) + D(1)/eta_d; ...
    E(2:end) - E(1:end-1) - eta_c*C(2:end) + D(2:end)/eta_d];
assert(max(abs(balanceResidual)) < 1e-5, '能量平衡核验失败。');
assert(max(abs(stateResidual)) < 1e-5, '储能状态核验失败。');
assert(all(C <= M + 1e-5) && all(D <= M + 1e-5), '功率约束核验失败。');
assert(all(E >= Emin - 1e-5) && all(E <= Emax + 1e-5), '容量约束核验失败。');
assert(abs(E(end) - E0) < 1e-5, '首尾储能不一致。');
assert(all((C < 1e-5) | (D < 1e-5)), '发现同一时段充、放电同时发生。');

%% 4. 写入题目模板（模板顺序为 00:10--00:20, ..., 00:00+1--00:10+1）
% 从内部日历顺序还原到模板顺序。
Graw = [G(2:end); G(1)];
Craw = [C(2:end); C(1)];
Draw = [D(2:end); D(1)];

copyfile(templateFile, outFile);
writematrix(Graw, outFile, 'Sheet', 1, 'Range', 'B2');

% 每四小时汇总按内部日历时间计算，不能依模板行号直接分组。
block = floor((0:n-1)'/24) + 1;
charge4h = accumarray(block, C, [6, 1], @sum);
discharge4h = accumarray(block, D, [6, 1], @sum);
writematrix([charge4h, discharge4h], outFile, 'Sheet', 2, 'Range', 'B2');
writematrix([E0; E(end)], outFile, 'Sheet', 2, 'Range', 'E2');

%% 5. 保存完整调度与摘要，便于复核和论文制表
internalTime = strcat(string(floor((0:n-1)'/6), '%02d'), ':', ...
    string(mod((0:n-1)'*10, 60), '%02d'));
schedule = table(internalTime, price, L, PV, G, C, D, W, E, ...
    'VariableNames', {'时段起点','电价_元每kWh','负荷_kWh','光伏可用_kWh', ...
    '购电_kWh','充电输入_kWh','放电输出_kWh','弃光_kWh','时段末储能_kWh'});
writetable(schedule, fullfile(outDir, 'q1_full_schedule.csv'), 'Encoding', 'UTF-8');

baselineGrid = max(L - PV, 0);
baselineCurtail = max(PV - L, 0);
baselineCost = sum(price .* baselineGrid);
summary = table(totalCost, sum(G), sum(C), sum(D), sum(W), baselineCost, sum(baselineGrid), ...
    baselineCost-totalCost, max(abs(balanceResidual)), max(abs(stateResidual)), ...
    'VariableNames', {'优化购电费_元','优化购电量_kWh','充电量_kWh','放电量_kWh', ...
    '弃光量_kWh','无储能购电费_元','无储能购电量_kWh','节省费用_元', ...
    '最大能量平衡残差_kWh','最大状态残差_kWh'});
writetable(summary, fullfile(outDir, 'q1_summary.csv'), 'Encoding', 'UTF-8');

fprintf('求解完成：优化购电费 %.4f 元，购电量 %.4f kWh，节省 %.4f 元。\n', ...
    totalCost, sum(G), baselineCost-totalCost);
fprintf('结果模板：%s\n', outFile);
