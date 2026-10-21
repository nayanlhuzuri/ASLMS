/**
 * Gathers the per-test results into `findings.json` and the contact sheet `index.html` (routes down, the three widths
 * across) in the run directory (design portal-ui-polish, decision 22). The exit status is Playwright's own: a test
 * fails on any finding.
 */
import { readdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

import type { Finding, ResultFile } from "./results";

const WIDTHS = ["375", "768", "1280"];

function esc(text: string): string {
  return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

export default function globalTeardown(): void {
  const dir = process.env.UICHECK_RUN_DIR;
  if (!dir) return;
  const results: ResultFile[] = readdirSync(join(dir, "results"))
    .filter((f) => f.endsWith(".json"))
    .map((f) => JSON.parse(readFileSync(join(dir, "results", f), "utf-8")) as ResultFile);
  const findings: Finding[] = results.flatMap((r) => r.findings);
  writeFileSync(join(dir, "findings.json"), JSON.stringify(findings, null, 2) + "\n");

  const byRoute = new Map<string, Map<string, ResultFile>>();
  for (const r of results) {
    const row = byRoute.get(r.name) ?? new Map<string, ResultFile>();
    row.set(String(r.width), r);
    byRoute.set(r.name, row);
  }
  const names = [...byRoute.keys()].sort();
  const screenshots = results.filter((r) => r.screenshot).length;
  const seconds = Math.round((Date.now() - Number(process.env.UICHECK_STARTED ?? Date.now())) / 1000);
  const rows = names
    .map((name) => {
      const cells = WIDTHS.map((w) => {
        const r = byRoute.get(name)!.get(w);
        if (!r) return "<td></td>";
        if (r.redirect) return `<td class="redirect">redirects to <code>${esc(r.redirect)}</code></td>`;
        const bad = r.findings.length ? `<ul>${r.findings.map((f) => `<li>${esc(f.kind)}: ${esc(f.element)} (${esc(f.detail)})</li>`).join("")}</ul>` : "";
        return `<td class="${r.findings.length ? "bad" : "ok"}"><a href="${esc(r.screenshot ?? "")}"><img loading="lazy" src="${esc(r.screenshot ?? "")}" alt="${esc(name)} at ${w} px"></a>${bad}</td>`;
      }).join("");
      return `<tr><th scope="row"><code>${esc(name)}</code></th>${cells}</tr>`;
    })
    .join("\n");
  const html = `<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>ASLMS browser check</title>
<style>
body{font:14px system-ui,sans-serif;margin:24px;color:#1f2937}
table{border-collapse:collapse;width:100%}
th,td{border:1px solid #d1d5db;padding:8px;vertical-align:top;text-align:left}
td img{display:block;max-width:100%;height:auto;max-height:520px;object-fit:contain;object-position:top}
td.bad{background:#fef2f2}td.redirect{color:#6b7280}
thead th{background:#f3f4f6;position:sticky;top:0}
</style></head><body>
<h1>ASLMS browser check</h1>
<p>${names.length} routes and states, ${screenshots} screenshots, ${findings.length} findings, ${seconds} s.</p>
<table><thead><tr><th>Route</th><th>375 px</th><th>768 px</th><th>1280 px</th></tr></thead><tbody>
${rows}
</tbody></table></body></html>
`;
  writeFileSync(join(dir, "index.html"), html);
  console.log(`uicheck: ${dir}: ${names.length} routes and states, ${screenshots} screenshots, ${findings.length} findings, ${seconds} s`);
}
