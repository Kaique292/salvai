import { mkdirSync, readFileSync, writeFileSync } from "node:fs";

const python = JSON.parse(readFileSync("build/coverage-python.json", "utf8")).totals;
const js = JSON.parse(readFileSync("build/coverage-js/coverage-summary.json", "utf8")).total;

const covered = python.covered_lines + js.lines.covered;
const total = python.num_statements + js.lines.total;
const pct = total ? Math.floor((covered / total) * 1000) / 10 : 0;
const color = pct >= 100 ? "2EA043" : pct >= 90 ? "97CA00" : pct >= 75 ? "DFB317" : "E5484D";

mkdirSync("docs/badges", { recursive: true });
writeFileSync(
  "docs/badges/coverage.json",
  JSON.stringify({ schemaVersion: 1, label: "cobertura", message: `${pct}%`, color }, null, 2) + "\n",
);
console.log(`cobertura ${pct}% (python ${python.percent_covered.toFixed(1)}%, interface ${js.lines.pct}%)`);
