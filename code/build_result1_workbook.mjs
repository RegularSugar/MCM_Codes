// 将 solve_q1_milp.m 的 CSV 结果写入题目提供的 result1.xlsx 模板。
// 此文件仅使用 artifact-tool 编辑工作簿，保留模板的两个工作表和原有时间标签。
import fs from "node:fs/promises";
import path from "node:path";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

async function locateProjectDir() {
  let candidate = path.resolve(import.meta.dirname);
  while (path.dirname(candidate) !== candidate) {
    try {
      await fs.access(path.join(candidate, "CUMCM2026Problems", "C题", "附件", "附件1.xlsx"));
      return candidate;
    } catch {
      candidate = path.dirname(candidate);
    }
  }
  throw new Error("未找到 CUMCM2026Problems/C题/附件/附件1.xlsx。");
}

const projectDir = await locateProjectDir();
const supportDir = path.resolve(import.meta.dirname, "..");
const isSupportSource = path.basename(import.meta.dirname) === "source"
  && path.basename(supportDir) === "第一问";
const outputDir = isSupportSource
  ? path.join(supportDir, "outputs")
  : path.join(projectDir, "outputs", "first_question");
const templatePath = path.join(projectDir, "CUMCM2026Problems", "C题", "附件", "附件5", "result1.xlsx");
const dataDir = isSupportSource ? outputDir : path.join(projectDir, "code", "outputs");
const finalPath = path.join(outputDir, "result1_第一问.xlsx");

function parseCsv(text) {
  const lines = text.trim().split(/\r?\n/);
  const headers = lines.shift().split(",");
  return lines.map((line) => Object.fromEntries(line.split(",").map((value, i) => [headers[i], value])));
}
async function readCsv(name) {
  return parseCsv(await fs.readFile(path.join(dataDir, name), "utf8"));
}

const [purchase, battery] = await Promise.all([
  readCsv("q1_schedule_template_order.csv"),
  readCsv("q1_battery_summary.csv"),
]);
if (purchase.length !== 144 || battery.length !== 6) {
  throw new Error("求解结果行数不正确，请先成功运行 solve_q1_milp.py。");
}

const input = await FileBlob.load(templatePath);
const workbook = await SpreadsheetFile.importXlsx(input);
const planSheet = workbook.worksheets.getItem("计划购电量");
const batterySheet = workbook.worksheets.getItem("充放电量");
const originalSheetNames = workbook.worksheets.items.map((sheet) => sheet.name);
const originalTimeLabels = planSheet.getRange("A2:A145").values.map(([label]) => label);

// 按官方结果模板原样保留 A2:A145 的时间标签；只填充数值列。
// 数值顺序与附件1原始144行一一对应。
const r4 = (value) => Math.round(Number(value) * 1e4) / 1e4;
planSheet.getRange("B2:B145").values = purchase.map((row) => [r4(row.grid_purchase_kWh)]);
batterySheet.getRange("B2:B7").values = battery.map((row) => [r4(row.charge_kWh)]);
batterySheet.getRange("C2:C7").values = battery.map((row) => [r4(row.discharge_kWh)]);
batterySheet.getRange("E2:E3").values = [[6000], [6000]];
planSheet.getRange("B2:B145").format.numberFormat = "0.0000";
batterySheet.getRange("B2:C7").format.numberFormat = "0.0000";
batterySheet.getRange("E2:E3").format.numberFormat = "0.0000";

const finalSheetNames = workbook.worksheets.items.map((sheet) => sheet.name);
const finalTimeLabels = planSheet.getRange("A2:A145").values.map(([label]) => label);
if (JSON.stringify(finalSheetNames) !== JSON.stringify(originalSheetNames)) {
  throw new Error("工作表结构发生了意外变化。");
}
if (JSON.stringify(finalTimeLabels) !== JSON.stringify(originalTimeLabels)) {
  throw new Error("官方模板的时间标签发生了意外变化。");
}

await fs.mkdir(outputDir, { recursive: true });
const inspect = await workbook.inspect({
  kind: "table",
  range: "计划购电量!A1:B145",
  include: "values,formulas",
  tableMaxRows: 6,
  tableMaxCols: 2,
});
console.log(inspect.ndjson);
const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!",
  options: { useRegex: true, maxResults: 50 },
  summary: "final formula error scan",
});
console.log(errors.ndjson);
const preview = await workbook.render({ sheetName: "充放电量", range: "A1:E7", scale: 2, format: "png" });
await fs.writeFile(path.join(outputDir, "result1_第一问_preview.png"), new Uint8Array(await preview.arrayBuffer()));
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(finalPath);
console.log(finalPath);
