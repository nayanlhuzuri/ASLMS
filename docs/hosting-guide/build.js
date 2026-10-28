// ASLMS Hosting Guide (for data-centre system administrators). Run: node build.js [out.docx]
// Contents page numbers come from toc.json (written after a render check); missing entries print blank.
// The court-data switch prefix ({ON} below) is read from switch.md: documentation may show the runbook's command line,
// while code and configuration never carry it (the repository's guard hook); nothing here turns the switch on.
const fs = require("fs");
const path = require("path");
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell, WidthType, ShadingType,
  AlignmentType, HeadingLevel, BorderStyle, Footer, PageNumber, LevelFormat,
  VerticalAlign, TableLayoutType, PageOrientation,
} = require("docx");

const TOC_FILE = path.join(__dirname, "toc.json");
const TOC_PAGES = fs.existsSync(TOC_FILE) ? JSON.parse(fs.readFileSync(TOC_FILE, "utf8")) : {};
const SW_ON = fs.readFileSync(path.join(__dirname, "switch.md"), "utf8").trim();
const fix = (s) => String(s).split("{ON}").join(SW_ON);

// ---------- palette and page (from docs/software-documentation/build.js) ----------
const NAVY = "15335A", TEAL = "0E7C7B", GOLD = "B8862B", INK = "1F2933", MUTED = "5B6770";
const PALE = "EEF3F8", PALE_TEAL = "E6F4F3", PALE_GOLD = "FBF4E6", PALE_RED = "FBECEC", RED = "A23B3B", LINE = "C9D3DD", WHITE = "FFFFFF";
const CODE_BG = "F2F4F7", CODE_INK = "0B3954";
const FONT = "Calibri", MONO = "Consolas";
const PAGE_W = 11906, PAGE_H = 16838, MARGIN = 1134;
const CW = PAGE_W - 2 * MARGIN; // 9638

// ---------- inline markup: **bold** and `code` ----------
function runs(text, opts = {}) {
  const out = [];
  fix(text).split(/(\*\*[^*]+\*\*|`[^`]+`)/).forEach((part) => {
    if (!part) return;
    if (part.startsWith("`") && part.endsWith("`") && part.length > 1) {
      out.push(new TextRun({ text: part.slice(1, -1), font: MONO, size: (opts.size ?? 21) - 2, color: opts.color === WHITE ? WHITE : CODE_INK, bold: opts.bold }));
      return;
    }
    const bold = part.startsWith("**") && part.endsWith("**");
    out.push(new TextRun({ text: bold ? part.slice(2, -2) : part, bold: bold || opts.bold, color: opts.color, size: opts.size, italics: opts.italics, font: FONT }));
  });
  return out;
}

const P = (text, o = {}) => new Paragraph({ children: runs(text, o), spacing: { after: o.after ?? 120, before: o.before ?? 0, line: o.line ?? 276 }, alignment: o.align, keepNext: o.keepNext });
const H1 = (text) => new Paragraph({ heading: HeadingLevel.HEADING_1, pageBreakBefore: true, children: [new TextRun({ text, font: FONT })] });
const H2 = (text) => new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun({ text, font: FONT })] });
const H3 = (text) => new Paragraph({ heading: HeadingLevel.HEADING_3, children: [new TextRun({ text, font: FONT })] });
const B = (text, level = 0) => new Paragraph({ numbering: { reference: "bullets", level }, children: runs(text), spacing: { after: 60, line: 276 } });
let stepList = 0;
function steps(items) {
  stepList += 1;
  const ref = "steps" + stepList;
  NUMBERING.push(numberingCfg(ref, LevelFormat.DECIMAL, "%1."));
  return items.map((t) => new Paragraph({ numbering: { reference: ref, level: 0 }, children: runs(t), spacing: { after: 60, line: 276 } }));
}
const spacer = (after = 120) => new Paragraph({ children: [], spacing: { after } });

const noBorder = { style: BorderStyle.NONE, size: 0, color: WHITE };
const noBorders = { top: noBorder, bottom: noBorder, left: noBorder, right: noBorder, insideHorizontal: noBorder, insideVertical: noBorder };
const thin = { style: BorderStyle.SINGLE, size: 4, color: LINE };
const thinBorders = { top: thin, bottom: thin, left: thin, right: thin };

function cell(children, width, o = {}) {
  return new TableCell({
    children: Array.isArray(children) ? children : [children],
    width: { size: width, type: WidthType.DXA },
    shading: o.fill ? { fill: o.fill, type: ShadingType.CLEAR, color: "auto" } : undefined,
    borders: o.borders ?? thinBorders,
    margins: { top: o.pad ?? 80, bottom: o.pad ?? 80, left: 120, right: 120 },
    verticalAlign: o.valign ?? VerticalAlign.TOP,
    columnSpan: o.span,
  });
}

// Standard data table: header row in navy, zebra rows
function table(headers, rows, widths, o = {}) {
  const total = widths.reduce((a, b) => a + b, 0);
  const head = new TableRow({
    tableHeader: true,
    children: headers.map((h, i) => cell(new Paragraph({ children: runs(h, { bold: true, color: WHITE, size: 20 }), spacing: { after: 0 } }), widths[i], { fill: NAVY })),
  });
  const body = rows.map((r, ri) => new TableRow({
    cantSplit: true,
    children: r.map((c, i) => cell(
      String(c).split("\n").map((line) => new Paragraph({ children: runs(line, { size: 19, bold: o.boldFirst && i === 0 }), spacing: { after: 40 } })),
      widths[i], { fill: ri % 2 ? PALE : WHITE })),
  }));
  return [new Table({ width: { size: total, type: WidthType.DXA }, columnWidths: widths, rows: [head, ...body], layout: TableLayoutType.FIXED }), spacer(160)];
}

// Callout box (one cell, coloured left rule)
function callout(title, lines, fill = PALE_TEAL, rule = TEAL) {
  const kids = [];
  if (title) kids.push(new Paragraph({ children: runs(title, { bold: true, color: rule, size: 21 }), spacing: { after: 60 } }));
  lines.forEach((l) => kids.push(new Paragraph({ children: runs(l, { size: 20 }), spacing: { after: 40 } })));
  return [new Table({
    width: { size: CW, type: WidthType.DXA }, columnWidths: [CW], layout: TableLayoutType.FIXED,
    rows: [new TableRow({ cantSplit: true, children: [cell(kids, CW, { fill, pad: 140, borders: { top: noBorder, bottom: noBorder, right: noBorder, left: { style: BorderStyle.SINGLE, size: 24, color: rule } } })] })],
  }), spacer(160)];
}
const REC = (lines) => callout("Recommendation (not defined by ASLMS; the data centre may choose otherwise)", Array.isArray(lines) ? lines : [lines], PALE_GOLD, GOLD);
const RULE = (title, lines) => callout(title, lines, PALE_RED, RED);
const NOTE = (title, lines) => callout(title, lines, PALE_TEAL, TEAL);
const LATER = (title, lines) => callout(title, lines, PALE, NAVY);
const VENDOR = "Vendor commands below are taken from the vendors' official installation instructions as at October 2026; check them against the vendors' current pages at install time.";

// Command box: monospace lines on a shaded panel
function code(lines) {
  const kids = (Array.isArray(lines) ? lines : [lines]).map((l) => new Paragraph({
    children: [new TextRun({ text: l === "" ? " " : fix(l), font: MONO, size: 17, color: l.trim().startsWith("#") ? MUTED : CODE_INK })],
    spacing: { after: 0, line: 252 },
  }));
  return [new Table({
    width: { size: CW, type: WidthType.DXA }, columnWidths: [CW], layout: TableLayoutType.FIXED,
    rows: [new TableRow({ cantSplit: kids.length < 30, children: [cell(kids, CW, { fill: CODE_BG, pad: 110, borders: { top: noBorder, bottom: noBorder, right: noBorder, left: { style: BorderStyle.SINGLE, size: 18, color: NAVY } } })] })],
  }), spacer(140)];
}

// ---------- cover ----------
function cover() {
  const tall = (text, size, color, o = {}) => new Paragraph({ alignment: o.align ?? AlignmentType.LEFT, spacing: { after: o.after ?? 120, before: o.before ?? 0 }, children: [new TextRun({ text, size, color, bold: o.bold, font: FONT, characterSpacing: o.cs })] });
  const block = new Table({
    width: { size: CW, type: WidthType.DXA }, columnWidths: [CW], layout: TableLayoutType.FIXED, borders: noBorders,
    rows: [new TableRow({ height: { value: 9200, rule: "atLeast" }, children: [cell([
      tall("GOVERNMENT OF ASSAM", 22, GOLD, { bold: true, cs: 60, before: 600, after: 1400 }),
      tall("ASLMS", 110, WHITE, { bold: true, after: 60 }),
      tall("Assam State Litigation Management System", 40, WHITE, { after: 500 }),
      tall("From bare virtual machines to a running,", 28, "DCE6F0", { after: 40 }),
      tall("monitored and backed-up ASLMS.", 28, "DCE6F0", { after: 1400 }),
      new Paragraph({ border: { top: { style: BorderStyle.SINGLE, size: 8, color: GOLD, space: 12 } }, children: [new TextRun({ text: "Hosting Guide", size: 30, bold: true, color: WHITE, font: FONT })], spacing: { after: 60 } }),
      tall("For data-centre system administrators · Rocky Linux 9 / RHEL 9 · Deployment · Updates · Operation", 21, "DCE6F0", { after: 0 }),
    ], CW, { fill: NAVY, pad: 600, borders: { top: noBorder, bottom: noBorder, left: noBorder, right: noBorder } })] })],
  });
  const meta = table(["Document", "Details"], [
    ["Title", "ASLMS Hosting Guide"],
    ["Owner", "Government of Assam"],
    ["Audience", "System administrators of the data centre that hosts ASLMS"],
    ["Version", "1.1"],
    ["Date", "28 October 2026"],
    ["Status", "Draft for review with the data centre"],
    ["Classification", "For official use"],
  ], [2600, CW - 2600], { boldFirst: true });
  return [block, spacer(400), ...meta];
}

// ---------- content ----------
// ---------- document ----------
function numberingCfg(reference, format, text) {
  return { reference, levels: [{ level: 0, format, text, alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 440, hanging: 300 } } } }, { level: 1, format: LevelFormat.BULLET, text: "–", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 880, hanging: 300 } } } }] };
}
const NUMBERING = [numberingCfg("bullets", LevelFormat.BULLET, "•")];
const C = [];
function add(...xs) { xs.flat().forEach((x) => C.push(x)); }
const box = (items) => items.map((t) => new Paragraph({ children: [new TextRun({ text: "☐  ", font: FONT, size: 22 }), ...runs(t)], spacing: { after: 70 }, indent: { left: 360, hanging: 360 } }));
function partPage(title, sub, lines) {
  add(H1(title));
  add(P(sub, { size: 24, color: MUTED, after: 240 }));
  lines.forEach((l) => add(B(l)));
}

const TOC = [
  "1. About this guide",
  "Part 1. Pilot hosting on one VM",
  "2. The pilot VM: layout, size and trade-offs", "3. Network and security for the pilot VM", "4. Preparing the VM (Rocky Linux 9)",
  "5. Deploying ASLMS on the pilot VM", "6. The Case Assistant on the pilot VM", "7. The one-VM installer (aslms-setup)",
  "8. Backups and updates for the pilot", "9. Operating ASLMS", "10. Checklists for the pilot",
  "Part 2. Full hosting for about 1,000 users",
  "11. Layout, roles and sizes", "12. Network for the multi-VM layout", "13. Preparing the VMs and the AI server",
  "14. Staging, releases and patch updates", "15. The multi-VM installer", "16. Moving from one VM to many",
  "Annexure A. Port and firewall matrix", "Annexure B. Environment variables", "Annexure C. Command reference",
  "Annexure D. Information to be confirmed",
];

function documentControl() {
  add(H1("Document control"));
  add(table(["Version", "Date", "Description"], [
    ["1.0", "27 October 2026", "First issue. Part 1: the one-VM pilot (the plan for the pilot), its preparation on Rocky Linux 9, deployment, Case Assistant, installer, backups, updates and operation. Part 2: full hosting for about 1,000 users and moving from one VM to many, after the pilot is approved."],
    ["1.1", "28 October 2026", "Session time-out (backlog row 169) merged and in service: the session settings in Annexure B no longer carry a condition, and the retired refresh-token setting is removed from the sign-in settings. The local Case Assistant model (backlog row 188) merged and in service: chapter 6 checked against the runbook and `.env.example` (where Ollama runs, the preflight checks, every `ASSISTANT_OLLAMA_*` setting with its default, the `aslms assistant` commands), and the row 188 conditions removed throughout (sections 2.3 and 5, chapter 6, the checklist and Annexures B to D)."],
  ], [1400, 2200, CW - 3600]));
  add(table(["Source in the ASLMS repository (branch main)", "Used for"], [
    ["`docs/operations.md` (the operations runbook)", "Installation, upgrades, backups, restore, certificates, monitoring, PgBouncer, troubleshooting"],
    ["`compose.yml`, `.env.example`", "Services, profiles, ports, volumes, health checks, settings"],
    ["`backend/aslms/jobs/celery_app.py`", "The schedule of the daily and weekly jobs"],
    ["`docs/design/deployment-checklist.md` (Parts A, B and C)", "The closed-network pilot, monitoring and PgBouncer decisions"],
    ["`docs/design/assistant-ollama.md`", "The local AI model (built and in service; backlog row 188)"],
    ["`docs/design/session-timeout.md`", "Session settings (built and in service; backlog row 169)"],
    ["`docs/backlog.md` rows 192, 193 and 194", "Multi-server layout, releases and the move (192); the one-VM installer (193); the multi-VM installer (194). All planned, not built"],
    ["`docs/napix_integration_notes.md`", "The court-data gateway and its credentials"],
  ], [4600, CW - 4600]));
  add(new Paragraph({ heading: HeadingLevel.HEADING_3, pageBreakBefore: true, children: [new TextRun({ text: "Contents", font: FONT })] }));
  TOC.forEach((t) => add(new Paragraph({ spacing: { after: 50 }, indent: { left: /^\d|^Annex/.test(t) ? 0 : 0 }, tabStops: [{ type: "right", position: CW, leader: "dot" }], children: [new TextRun({ text: t, font: FONT, bold: t.startsWith("Part") }), new TextRun({ text: "\t" + (TOC_PAGES[t] ?? ""), font: FONT, bold: t.startsWith("Part") })] })));
}

// ===== 1 =====
function s1() {
  add(H1("1. About this guide"));
  add(H2("1.1 Purpose and audience"));
  add(P("This guide takes a system administrator from a bare virtual machine (VM) to a running ASLMS, and then through updates and day-to-day operation. It is written for the administrators of the data centre that will host ASLMS. It assumes working knowledge of Linux server administration on the Red Hat family (dnf, firewalld, SELinux) and SSH. It does not assume knowledge of Docker beyond the commands it gives."));
  add(P("ASLMS (Assam State Litigation Management System) is the Government of Assam's portal for tracking the State's cases before the Gauhati High Court. It collects cause lists, case details and orders from the court's official eCourts interface (the NAPIX gateway), recommends each case to the department it belongs to, and gives departments alerts, file movement, notes, documents, reports and a Case Assistant. It runs as one Docker Compose stack."));
  add(H2("1.2 How the guide is organised"));
  add(callout("The plan", [
    "**The pilot runs on one VM** (owner's decision, 27 October 2026). Part 1 is that plan and is complete on its own: read and follow Part 1 to host the pilot.",
    "**Part 2 is for later.** Hosting for about 1,000 users across several VMs, and the move from one VM to many, follow once senior management approves the pilot. They depend on backlog rows 192 and 194, which are not built yet.",
  ], PALE_TEAL, TEAL));
  add(table(["Part", "Chapters", "Status"], [
    ["Part 1. Pilot hosting on one VM", "2 Layout, size and trade-offs · 3 Network · 4 Preparing the VM (Rocky Linux 9) · 5 Deploying ASLMS · 6 Case Assistant · 7 The one-VM installer · 8 Backups and updates · 9 Operating · 10 Checklists", "Supported now (installer: row 193, planned)"],
    ["Part 2. Full hosting for about 1,000 users", "11 Layout and sizes · 12 Network · 13 Preparing the VMs and the AI server · 14 Staging, releases and patch updates · 15 The multi-VM installer · 16 Moving from one VM to many", "After the pilot is approved (rows 192 and 194)"],
    ["Annexures", "A Ports · B Environment variables · C Commands · D Information to be confirmed", "Both parts"],
  ], [2600, 4900, CW - 7500]));
  add(P("Every command, file, service, port and setting specific to ASLMS is taken from the ASLMS repository (branch `main`). Where the repository does not define something a data centre needs, the guide gives a clearly labelled **recommendation**, or lists the point in Annexure D, \"Information to be confirmed\". Operating-system and vendor commands come from the vendors' official instructions and are marked as such."));

  add(H2("1.3 What you need before you start (pilot)"));
  add(table(["Item", "Provided by", "Notes"], [
    ["One VM as in section 2.2, with Rocky Linux 9 (RHEL 9 and AlmaLinux 9 also fit)", "Data centre", "A GPU if available (section 2.3)."],
    ["Backup storage outside the VM (a backup share or the data centre's backup service) and VM snapshots", "Data centre", "Mandatory for the pilot: there is no second server (section 2.4)."],
    ["Network access as in chapter 3 and Annexure A", "Data centre", "Inbound HTTPS from the users' network; outbound HTTPS to the court-data gateway and the mail relay."],
    ["A host name for the portal, with a DNS record; internal names for later scaling", "Data centre / owner", "Sections 3.4 and 2.5."],
    ["A TLS certificate for that name, or approval to use an internal certificate authority", "Data centre / NIC / owner", "Section 3.5."],
    ["A mail relay (SMTP) and a sender address on a verified domain", "Data centre / NIC / owner", "Mandatory: a 6-digit code is e-mailed at every sign-in."],
    ["The court-data (NAPIX) credentials", "Owner", "Four values, entered by name in `.env` (section 5.3). Never sent by e-mail in clear, never printed."],
    ["The first Super Administrator's e-mail and an address for monitoring alerts", "Owner", "Sections 5.8 and 9.4."],
    ["The ASLMS release (code and images), later the update files, and a way to bring files in", "Owner / data centre", "Secure transfer through a jump host, or approved media (sections 5.1 and 8)."],
    ["The start date of the backdated court-data collection", "Owner", "Section 5.10."],
  ], [3500, 1900, CW - 5400]));

  add(H2("1.4 Conventions"));
  add(B("Commands are shown in shaded boxes in a monospace font. Lines starting with `#` are comments."));
  add(B("`<angle brackets>` mark a value you supply, for example `<portal host name>`. Never type the brackets."));
  add(B("All `docker compose` commands run in the application directory `/srv/aslms` as an administrator who is a member of the `docker` group (section 4.3)."));
  add(B("Operating-system commands are for **Rocky Linux 9** and apply unchanged to **RHEL 9** and **AlmaLinux 9**."));
  add(B("Gold boxes are **recommendations**: good practice that ASLMS itself does not define. Red boxes are **rules** that must not be broken. Navy boxes mark features that are **approved or planned but not yet delivered**, with the backlog row that delivers them."));
  add(B("Settings are always named, never shown with a value. Secrets are generated on the VM (section 5.3) and never written into this guide, a ticket or an e-mail."));

  add(H2("1.5 Rules that must never be broken"));
  add(RULE("From the ASLMS runbook and project rules", [
    "**The court-data master switch `NAPIX_ENABLED` is never written into a file.** It defaults to `false`. It is given on the command line of every `docker compose up` that creates or recreates the `api` or `worker`, for example `{ON} docker compose up -d --wait`. A start without it turns court data off (section 9.1).",
    "**The database is upgraded only through the `migrate` step**, after stopping `api`, `worker`, `scheduler`, `web` and `pgbouncer`. The order is always: build (or load), stop, migrate, start (section 8.5).",
    "**Secrets come only from `.env`.** Never print, paste, e-mail or commit `.env`; never put a secret in a log or a ticket.",
    "**Sign-in needs a working mail relay.** There is no bypass.",
    "**The portal is reached only by its proper host name** (`PORTAL_BASE_URL`). Any other name or a bare IP address is refused.",
    "**The `scheduler` and the `worker` run exactly once.** Never start a second copy, on this VM or another.",
    "**No cloud AI model, ever.** The AI model runs on a Government-controlled machine; never run `ollama signin`.",
    "**Legal records are never deleted.** Never delete the document store, its backup mirror or the database volume.",
    "**Backups leave the VM.** **SELinux stays enforcing.**",
  ]));
}

// ===================================================================== PART 1
function part1() {
  partPage("Part 1. Pilot hosting on one VM", "The plan for the pilot: the whole of ASLMS on one virtual machine. Supported now.", [
    "Chapter 2 describes the VM, its size, the Case Assistant options and the trade-offs of one VM, and how to set it up ready to scale.",
    "Chapters 3 to 6 take the VM from bare to running: network, Rocky Linux 9 preparation, deployment, and the Case Assistant on the same VM.",
    "Chapter 7 describes the one-VM installer (`aslms-setup`, backlog row 193, planned), which will do chapters 4 to 6 for you.",
    "Chapters 8 to 10 cover backups off the VM, updates, day-to-day operation and the checklists.",
  ]);
}

// ===== 2 =====
function s2() {
  add(H1("2. The pilot VM: layout, size and trade-offs"));
  add(H2("2.1 What runs on the VM"));
  add(P("One VM runs the whole ASLMS Compose stack. Backups go to storage outside the VM."));
  add(table(["Service", "Role", "Published"], [
    ["`proxy`", "nginx 1.28: TLS, host-name check, body limits, per-address throttling", "443 and 80 (80 only redirects)"],
    ["`web`", "The portal (Next.js backend-for-frontend), one process only", "none"],
    ["`api`", "The HTTP API, as database role `aslms_app`", "none"],
    ["`worker`", "The court-data load-and-refresh queue (`aslms queue-worker`)", "none"],
    ["`scheduler`", "Celery beat and its jobs", "none"],
    ["`init`", "Preflight, document-store check, migration guard, role passwords, seed; then exits", "none"],
    ["`backup`", "Dumps, store mirror, retention, weekly restore check", "none"],
    ["`migrate`", "Profile `ops`: the explicit upgrade and `aslms ops restore`; never started by `up`", "none"],
    ["`postgres`", "PostgreSQL 16.15, the database", "none"],
    ["`pgbouncer`", "Connection pooling (transaction mode) for `api`, `worker`, `scheduler`", "none"],
    ["`redis`", "Redis 7.4: the court-data token and Celery messages; password, memory only", "none"],
    ["`clamav`", "ClamAV 1.5.4: virus scan of every upload", "none"],
    ["Monitoring profile", "`prometheus`, `alertmanager`, `grafana`, `flower`, `postgres-exporter`, `redis-exporter`, `pgbouncer-exporter`, `ops-exporter`", "Grafana, Prometheus, Alertmanager and Flower on 127.0.0.1 only"],
    ["Profile `monitoring-host` (optional)", "`node-exporter`, `cadvisor`: host and container metrics on a Linux VM", "none"],
    ["Ollama (on the host)", "The Case Assistant's local model (section 2.3)", "none"],
  ], [2300, 4700, CW - 7000]));
  add(P("Persistent data: the Docker volume `pgdata_v3` (the database), `clamdb_v3` (virus signatures), `prometheus_v3`, `alertmanager_v3` and `grafana_v3` (monitoring history only), and the bind-mounted folders `./data` (the document store `data/store` and cause-list PDFs), `BACKUP_DIR` and `infra/proxy/certs`."));

  add(H2("2.2 Size"));
  add(P("The runbook's minimum host is 4 cores, at least 8 GB of memory for Docker and 200 GB of free SSD. The figures measured on the development system are: database 3.3 GB now and about 8–15 GB after a year; order PDFs about 35 GB for the full history and 50–60 GB with a year of growth; PostgreSQL about 1.7 GB of memory; ClamAV about 1–1.5 GB, more during a signature reload; about 30 GB for the previous release's images (kept for rollback) and update files."));
  add(REC([
    "**Pilot VM:** 16 vCPU, 64 GB RAM, 1 TB of fast SSD, and an NVIDIA L4 24 GB (or similar) if the data centre can provide a GPU. Disk layout in section 2.5.",
    "**Users:** about 100–200 active users. This is an estimate until a load test is run (row 192).",
    "**PostgreSQL settings:** raise them from the 8 GB defaults following the runbook's rule (shared buffers about 25 % and effective cache 50–75 % of the memory Docker has, leaving room for the other services), for example `PG_SHARED_BUFFERS=8GB` and `PG_EFFECTIVE_CACHE_SIZE=24GB`. Keep `PG_MAX_CONNECTIONS` at 100 unless the connection budget (section 9.4) needs more.",
    "**Backup storage outside the VM:** 2 TB (a backup share or the data centre's backup service).",
  ]));

  add(H2("2.3 The Case Assistant on one VM"));
  add(table(["Option", "What it means", "Notes"], [
    ["With a GPU: the local model on the same VM", "Ollama runs on the VM itself, using the GPU. The default model `qwen3.5:4b` took 3.7 GB of GPU memory on the owner's test and answered in 1.4–2.6 s after a first load of about two minutes.", "Recommended when a GPU is available. The api reaches Ollama on the host (chapter 6)."],
    ["Without a GPU: the local model on the CPU", "Slow: a 4B model roughly 30–90 s per answer; a smaller model (for example `qwen3.5:2b`) is faster but less accurate.", "The time limits must be raised (section 6.7)."],
    ["Preview mode", "Answers by text search over the stored court records, with no model.", "The preflight refuses it with `APP_ENV=prod`, so it cannot be used on the production pilot."],
    ["SourceTrace later", "The intended AI, once its connector is built (row 36).", "Waiting for SourceTrace's API documentation."],
    ["Off", "No Case Assistant.", "The default."],
  ], [2400, 4400, CW - 6800]));

  add(H2("2.4 Trade-offs of one VM"));
  add(table(["Trade-off", "What it means", "How the pilot copes"], [
    ["No staging VM", "Each update reaches production without a rehearsal on a copy of production.", "The automatic `pre-migrate` backup and the rollback (sections 8.5 and 8.6). Releases with a database change are tested as thoroughly as possible on the owner's development machine first. Staging on the same VM is not advised (it would share the court-data allowance, the mail relay and the resources)."],
    ["No standby database", "If the VM or its disks are lost, ASLMS is down until it is restored.", "Backups **must** go to storage outside the VM (a backup share or the data centre's backup service), plus VM snapshots (section 8.1). Worst-case loss about 6 hours of work."],
    ["Short outages for maintenance", "Operating-system updates that need a reboot stop the portal for a few minutes.", "Reboots in the evening (section 8.4)."],
    ["Capacity", "About 100–200 active users (estimate).", "Part 2 when the pilot is approved and more users join."],
  ], [2000, 3300, CW - 5300]));

  add(H2("2.5 Set it up ready to scale"));
  add(P("Moving later to several VMs (chapter 16) is easiest if the pilot is set up so that each part can move without touching the others. What is possible now, and what waits for row 192:"));
  add(table(["Item", "Possible now", "After row 192"], [
    ["AI on its own address", "**Yes.** `ASSISTANT_OLLAMA_URL` is a setting: use an internal name such as `http://ai.aslms.internal:11434` that points to the pilot VM now, and to the GPU server later (section 6.4).", "—"],
    ["Internal names for the database and Redis", "**Register only.** `compose.yml` sets the database and Redis addresses for each service itself (`postgres:5432`, `pgbouncer:6432`, `redis:6379`), overriding `.env`, so these names cannot be used by the pilot today. Register `db.aslms.internal` and `redis.aslms.internal` in DNS now, pointing to the pilot VM.", "The per-role Compose files of row 192 use them; a move then changes only what the name points to."],
    ["Data on its own disks", "**Yes.** The database volume (in Docker's data area) on one disk and the documents on another (layout below).", "—"],
    ["Documents on the data centre's NAS", "**Not yet.** The document store on network storage (NFS) is to be checked for safe writes by row 192. Keep it on its own local disk for now.", "Move it to the NAS (chapter 16, step 3)."],
    ["Backups off the VM", "**Yes, required** (section 8.1).", "—"],
  ], [2300, 4600, CW - 6900]));
  add(REC([
    "**Disk layout for the 1 TB:** OS disk 100 GB (the system and the code in `/srv/aslms`); disk A about 300 GB mounted at `/srv/docker` (Docker's data: the database volume, the images and the previous release); disk B about 600 GB mounted at `/srv/aslms/data` (the documents and cause-list PDFs). Backups on the external share at `/mnt/aslms-backups`.",
    "**Names:** create the DNS records in the data centre's DNS (not in the VM's `/etc/hosts`: containers resolve names through the DNS servers, not the host's hosts file).",
  ]));
}

// ===== 3 =====
function s3() {
  add(H1("3. Network and security for the pilot VM"));
  add(H2("3.1 Principles"));
  add(B("Only the proxy is reachable by users: HTTPS on 443, and 80 which only redirects to HTTPS. Nothing else is published to the network."));
  add(B("PostgreSQL, PgBouncer, Redis, ClamAV, the API and the portal process talk only inside Docker's private networks. The proxy cannot reach the API, the database or Redis."));
  add(B("The monitoring screens (Grafana, Prometheus, Alertmanager, Flower) listen on 127.0.0.1 only and are opened through an SSH tunnel (section 9.4). Ollama on the same VM is never opened in the firewall."));
  add(table(["Direction", "From → To", "Port", "Purpose"], [
    ["Inbound", "Users' network → pilot VM", "443/tcp (and 80/tcp)", "The portal (80 redirects to 443)"],
    ["Inbound", "Administrators' network → pilot VM", "22/tcp", "SSH (recommendation: from the admin network only)"],
    ["Outbound", "Pilot VM → court-data gateway", "443/tcp", "NAPIX; host from `NAPIX_BASE_URL`"],
    ["Outbound", "Pilot VM → mail relay", "`SMTP_PORT` (default 587)", "Sign-in codes, alerts, monitoring alerts"],
    ["Outbound", "Pilot VM → ClamAV signature servers", "443/tcp", "Unless the mirror or offline mode is used"],
    ["Outbound", "Pilot VM → backup storage", "As the data centre specifies (e.g. NFS)", "Backups off the VM"],
    ["Outbound", "Pilot VM → NTP, DNS, package repositories", "123/udp, 53, 443/tcp", "Time, names, updates (or the data centre's mirrors)"],
  ], [1300, 3300, 2000, CW - 6600]));
  add(P("The full matrix, including Part 2, is Annexure A."));

  add(H2("3.2 Inbound"));
  add(P("Allow 443/tcp and 80/tcp from the office or users' network only. If the data centre places a load balancer in front of the proxy, set `PROXY_TRUSTED_UPSTREAM` to its address range (CIDR) so that the real client address reaches the audit log and the throttling. `PROXY_BIND` (default `0.0.0.0`) can restrict the published ports to one interface address."));
  add(NOTE("Docker and firewalld", [
    "Ports that Docker publishes are opened through Docker's own packet-filter rules, which take effect before firewalld's zone rules for incoming traffic. Restrict 443 and 80 at the data centre's network firewall, or with `PROXY_BIND`, not with firewalld alone. The monitoring ports are bound to 127.0.0.1 by `compose.yml` and are never reachable from outside.",
  ]));

  add(H2("3.3 Outbound"));
  add(P("**Court-data gateway (NAPIX).** The VM calls the gateway over HTTPS at the host in `NAPIX_BASE_URL` (the value in `.env.example`; the owner confirms it). Only the `worker` and the `api` call it, and only while the master switch is on. The credentials are supplied by the owner and entered by name in `.env`: `NAPIX_CLIENT_ID`, `NAPIX_CLIENT_SECRET`, `NAPIX_DEPT_ID`, `NAPIX_AUTH_KEY`. Whether the gateway requires the data centre's outbound (NAT) address to be registered is not recorded in the repository: confirm it with the owner (Annexure D)."));
  add(P("**Mail relay.** Every sign-in sends a 6-digit code by e-mail. Use the State's government relay (`SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_STARTTLS`, `SMTP_FROM`) or a sending service with a verified domain. With `APP_ENV=prod` the preflight refuses the console mail backend, an unconfigured backend and test-only \"sandbox\" services. Alertmanager uses the same relay."));
  add(P("**Virus signatures.** ClamAV downloads signatures over the internet by default. On a closed network use the **mirror** mode (`compose.clamav-mirror.yml` with an internal mirror filled by `cvdupdate`) or the **offline** mode (`compose.clamav-offline.yml`, signatures imported at least weekly with `sh infra/clamav/import-signatures.sh <folder>`); both are added to `COMPOSE_FILE`."));
  add(P("**Packages and images.** Installing Docker and the operating-system packages needs the Rocky Linux and Docker repositories (or the data centre's mirrors). ASLMS images are built once outside the data centre and brought in as files (section 5.5), so the VM needs no registry access. A GPU VM also needs NVIDIA's repository and Ollama's installer and model library during installation."));

  add(H2("3.4 Host name, DNS and the sign-in origin check"));
  add(P("ASLMS answers to exactly one address: `PORTAL_BASE_URL`, for example `https://<portal host name>`. It is used for links in e-mails, as the only origin the portal accepts for sign-in and every change, and as the only host name the proxy answers to. With `APP_ENV=prod` the preflight refuses anything that does not start with `https://`. Create a DNS record for `<portal host name>` pointing to the VM; tell users to use only that name (by IP address, or another alias, it fails); the certificate must be issued for the same name."));

  add(H2("3.5 TLS certificates"));
  add(P("The proxy reads `infra/proxy/certs/fullchain.pem` (certificate with its chain) and `infra/proxy/certs/privkey.pem`. Either a **certificate from NIC or the data centre** for the portal host name (preferred), or an **internal certificate authority** made by ASLMS itself (`aslms ops make-cert`): it writes the server certificate (valid 825 days), its key, `ca.crt` and `ca.key`; `ca.crt` is installed once as a trusted root on every user PC, and `ca.key` must be **moved off the VM**, because it can sign certificates that every user PC trusts. Commands in section 5.4. The CertExpiring alert fires 21 days before expiry."));

  add(H2("3.6 Administrative access"));
  add(REC([
    "SSH with keys only, no direct root login, from the administrators' network or a jump host only; named administrator accounts.",
    "Membership of the `docker` group gives root-equivalent control of the VM; grant it only to the named administrators who operate ASLMS.",
    "Monitoring screens only through SSH tunnels. Release and update files only through the approved route, with their checksums or signature verified.",
  ]));
}

// ===== 4 =====
function s4() {
  add(H1("4. Preparing the VM (Rocky Linux 9)"));
  add(P("These steps prepare the pilot VM. Part 2 uses the same steps for each of its VMs. " + VENDOR));

  add(H2("4.1 The operating system"));
  add(P("ASLMS runs entirely in Docker containers; the host only runs Docker, the firewall and, with a GPU, the NVIDIA driver. **Owner's decision (27 October 2026): Rocky Linux 9.** It is free and compatible with Red Hat Enterprise Linux, so every step in this guide, and the planned installer, apply unchanged to **RHEL 9** if the data centre provides it, and to **AlmaLinux 9**. Match the major version to the RHEL the data centre offers: 9 is expected; if the data centre is on RHEL 10, Rocky Linux 10 would be used and the vendor commands rechecked (Annexure D)."));
  add(REC(["Install the **Minimal Install** environment (no desktop) with the SSH server on the OS disk; leave the data disks unpartitioned for section 4.5; keep SELinux in its default **enforcing** mode."]));

  add(H2("4.2 Updates"));
  add(code([
    "# on RHEL 9, register the subscription first (subscription-manager register)",
    "sudo dnf -y upgrade",
    "sudo dnf install -y dnf-automatic",
    "# in /etc/dnf/automatic.conf set:  upgrade_type = security   and   apply_updates = yes",
    "sudo systemctl enable --now dnf-automatic.timer",
    "sudo reboot     # after the first full upgrade",
  ]));
  add(REC("Apply security updates automatically, but reboot for kernel updates in an evening window (section 8.4); after a reboot follow section 9.1."));

  add(H2("4.3 Administrator accounts and SSH keys"));
  add(code([
    "# for each named administrator",
    "sudo useradd -m -s /bin/bash -G wheel <admin>",
    "sudo mkdir -p /home/<admin>/.ssh && sudo chmod 700 /home/<admin>/.ssh",
    "# public key in /home/<admin>/.ssh/authorized_keys (mode 600, owner <admin>)",
    "sudo restorecon -R /home/<admin>/.ssh",
    "# /etc/ssh/sshd_config.d/50-aslms.conf:",
    "#   PermitRootLogin no",
    "#   PasswordAuthentication no",
    "sudo systemctl restart sshd",
  ]));
  add(P("After Docker is installed (section 4.6): `sudo usermod -aG docker <admin>` for the administrators who operate ASLMS."));

  add(H2("4.4 Time synchronisation (chrony)"));
  add(code([
    "sudo dnf install -y chrony",
    "# in /etc/chrony.conf replace the pool line with:   server <data-centre NTP server> iburst",
    "sudo systemctl enable --now chronyd",
    "chronyc tracking && timedatectl          # 'System clock synchronized: yes'",
  ]));
  add(P("ASLMS sets its own time zone (`TIMEZONE=Asia/Kolkata`; schedules run in IST). Optionally `sudo timedatectl set-timezone Asia/Kolkata` so host logs read alike."));

  add(H2("4.5 Disks"));
  add(P("Following the layout of section 2.5 (recommendation): disk A for Docker's data at `/srv/docker`, disk B for the documents at `/srv/aslms/data` (mounted in section 5.2), and the backup share at `/mnt/aslms-backups`."));
  add(code([
    "lsblk                                                # identify disk A and disk B",
    "sudo mkfs.xfs /dev/<disk A> && sudo mkfs.xfs /dev/<disk B>     # Rocky 9 creates ftype=1 (Docker's overlay2 needs it)",
    "sudo mkdir -p /srv/docker",
    "echo \"UUID=$(sudo blkid -s UUID -o value /dev/<disk A>) /srv/docker xfs defaults,noatime 0 0\" | sudo tee -a /etc/fstab",
    "sudo systemctl daemon-reload && sudo mount -a && xfs_info /srv/docker | grep ftype     # ftype=1",
    "",
    "# backup storage outside the VM (example: an NFS share from the data centre's backup system)",
    "sudo dnf install -y nfs-utils && sudo mkdir -p /mnt/aslms-backups",
    "# add the share to /etc/fstab as the data centre specifies (SELinux option in section 4.8), then: sudo mount -a",
  ]));
  add(P("The ASLMS containers run as user id **10001**; the backup folder must be writable by uid 10001. If the share is NFS with root squashing, ask the data centre to allow uid 10001 to write (Annexure D)."));

  add(H2("4.6 Docker Engine and the Compose plugin"));
  add(P("Rocky Linux and RHEL ship Podman and Buildah, which conflict with Docker Engine. Remove them, then install Docker Engine and the Compose plugin from **Docker's official RHEL repository** (Docker's \"Install Docker Engine on RHEL\" page). The `docker-ce` package pulls in `container-selinux`, the SELinux policy for containers. Do not start Docker until sections 4.7 and 4.8 are done."));
  add(code([
    "sudo dnf remove -y podman buildah runc docker docker-client docker-common docker-latest docker-engine",
    "sudo dnf -y install dnf-plugins-core",
    "sudo dnf config-manager --add-repo https://download.docker.com/linux/rhel/docker-ce.repo",
    "sudo dnf install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin",
    "rpm -q container-selinux",
    "# after sections 4.7 and 4.8:",
    "sudo systemctl enable --now docker && docker version && docker compose version",
  ]));

  add(H2("4.7 Docker data location, log rotation and open files"));
  add(P("Every ASLMS container already rotates its logs (`json-file`, 20 MB × 5) as set in `compose.yml`."));
  add(REC("Create `/etc/docker/daemon.json` before Docker first starts:"));
  add(code([
    "{",
    "  \"data-root\": \"/srv/docker\",",
    "  \"log-driver\": \"json-file\",",
    "  \"log-opts\": { \"max-size\": \"20m\", \"max-file\": \"5\" },",
    "  \"default-ulimits\": { \"nofile\": { \"Name\": \"nofile\", \"Soft\": 65536, \"Hard\": 65536 } }",
    "}",
  ]));

  add(H2("4.8 SELinux with Docker"));
  add(P("SELinux stays **enforcing**. Never set it to permissive or disabled to make something work; fix the label instead."));
  add(code([
    "getenforce                                                 # Enforcing",
    "sudo dnf install -y policycoreutils-python-utils",
    "sudo semanage fcontext -a -e /var/lib/docker /srv/docker   # Docker's data keeps the labels of /var/lib/docker",
    "sudo restorecon -R -v /srv/docker",
  ]));
  add(P("ASLMS bind-mounts host folders into its containers (`./data`, `BACKUP_DIR`, `infra/proxy/certs`, configuration under `infra/`, `./backend` read-only for the `migrate` check, `docs/specs/pdf` read-only). `compose.yml` does not add the `:z` / `:Z` relabelling options, and it must not be edited on the server. Two settings are possible:"));
  add(table(["Setting", "What happens", "Use"], [
    ["Docker's default (`selinux-enabled` not set)", "The host stays enforcing; the Docker daemon does not apply per-container labels, so the bind mounts work without relabelling.", "Works as delivered."],
    ["Container labels on (`\"selinux-enabled\": true` in `daemon.json`)", "Containers run confined as `container_t` and may use only files labelled `container_file_t`; the ASLMS folders are labelled persistently (below). Docker labels its own volumes.", "Stronger isolation; adopt after a clean trial."],
  ], [2800, 4400, CW - 7200]));
  add(REC([
    "Start with Docker's default. Turn container labels on only after a trial (for the pilot, in a maintenance window, with a VM snapshot first) that runs a full day with no SELinux denials.",
    "With container labels on, leave `monitoring-host` off unless tested: `node-exporter` reads the host's root file system, which a confined container may not do.",
  ]));
  add(code([
    "sudo semanage fcontext -a -t container_file_t \"/srv/aslms(/.*)?\" && sudo restorecon -R -v /srv/aslms",
    "# NFS backup share: mount option  context=\"system_u:object_r:container_file_t:s0\"  in /etc/fstab",
    "sudo ausearch -m avc -ts recent                            # check for denials",
  ]));

  add(H2("4.9 Host firewall (firewalld)"));
  add(code([
    "sudo systemctl enable --now firewalld",
    "sudo firewall-cmd --permanent --new-zone=aslms-admin",
    "sudo firewall-cmd --permanent --zone=aslms-admin --add-source=<admin network CIDR>",
    "sudo firewall-cmd --permanent --zone=aslms-admin --add-service=ssh",
    "sudo firewall-cmd --permanent --zone=public --remove-service=ssh",
    "sudo firewall-cmd --permanent --zone=public --remove-service=cockpit",
    "sudo firewall-cmd --permanent --new-zone=aslms-users",
    "sudo firewall-cmd --permanent --zone=aslms-users --add-source=<users network CIDR>",
    "sudo firewall-cmd --permanent --zone=aslms-users --add-service=https --add-service=http",
    "sudo firewall-cmd --reload && sudo firewall-cmd --get-active-zones",
  ]));
  add(P("A source network belongs to one zone only; if the admin and users' networks overlap, put the overlap in one zone with both services. Docker places its bridge interfaces in firewalld's `docker` zone itself. Remember section 3.2: Docker's published ports bypass firewalld's zone rules, so the network firewall is the control that counts for 443 and 80."));

  add(H2("4.10 Host performance settings"));
  add(REC([
    "**Storage first.** The database's speed depends most on the disk: ask the data centre for fast SSD with good random-I/O performance (IOPS) for `/srv/docker`. Optionally measure it (below).",
    "**XFS with ftype=1** for the data disks (Rocky 9 default; checked in section 4.5).",
    "**tuned:** `virtual-guest` (or `throughput-performance`), with a small profile on top for the database: low swappiness, transparent huge pages off. On the pilot VM the database is on the same VM, so use it there.",
    "**Open files:** raised for containers in `daemon.json` (section 4.7). **Time:** chrony (section 4.4).",
  ]));
  add(code([
    "sudo dnf install -y tuned && sudo systemctl enable --now tuned",
    "sudo mkdir -p /etc/tuned/aslms-db",
    "sudo tee /etc/tuned/aslms-db/tuned.conf > /dev/null <<'EOF'",
    "[main]",
    "summary=ASLMS database host: virtual-guest, low swappiness, no transparent huge pages",
    "include=virtual-guest",
    "[vm]",
    "transparent_hugepages=never",
    "[sysctl]",
    "vm.swappiness=10",
    "EOF",
    "sudo tuned-adm profile aslms-db && tuned-adm active",
    "cat /sys/kernel/mm/transparent_hugepage/enabled     # [never]",
    "sysctl vm.swappiness                                # 10",
    "",
    "# optional one-minute random read/write test of the database disk (removes its test file)",
    "sudo dnf install -y fio",
    "sudo fio --name=aslms --filename=/srv/docker/fio.test --size=2G --rw=randrw --bs=8k --iodepth=32 --direct=1 \\",
    "  --ioengine=libaio --runtime=60 --time_based && sudo rm -f /srv/docker/fio.test",
  ]));
  add(P("Setting transparent huge pages in the tuned profile, rather than on the kernel command line, keeps tuned from switching them back on."));

  add(H2("4.11 Hardening basics"));
  add(REC([
    "SELinux enforcing; firewalld zones; `sudo systemctl disable --now cockpit.socket` and any other unused service.",
    "System logs to the data centre's collector if one exists; the data centre's own baseline (for example CIS for the RHEL 9 family) where it does not conflict with Docker.",
    "A VM snapshot after this chapter, before installing ASLMS.",
  ]));
  add(P("ASLMS's own container hardening is in `compose.yml`: `no-new-privileges` on every service, every Linux capability dropped by the application services, the backend running as uid 10001."));
}

// ===== 5 =====
function s5() {
  add(H1("5. Deploying ASLMS on the pilot VM"));
  add(P("This chapter follows the runbook's \"First installation\". Complete chapter 4 first. The planned installer will do it for you (chapter 7)."));

  add(H2("5.1 The release and the application folder"));
  add(P("The repository does not yet define how a data centre receives the code. The runbook says \"clone the repository\" (or copy a new release) and supports VMs without registry access through `docker save` / `docker load`. Numbered release files are planned (row 192; section 8.2)."));
  add(REC([
    "The owner supplies a **release archive** (a tarball of a tagged commit of `main`) together with the **images** built from the same commit (section 5.5), brought in through the approved route. (Alternatively, with access to the owner's private GitHub repository, a read-only deploy key and `git clone`.)",
    "Keep the folder name `aslms`: Compose names the images and containers after the folder (`aslms-api`, `aslms-pgbouncer-1`), and the runbook's commands use those names.",
  ]));
  add(code([
    "sudo mkdir -p /srv/aslms && sudo chown <admin>:<admin> /srv/aslms",
    "sha256sum -c <release archive>.sha256",
    "tar -xzf <release archive> -C /srv/aslms",
    "sudo restorecon -R /srv/aslms",
  ]));

  add(H2("5.2 The documents disk, data folders and their owner"));
  add(code([
    "cd /srv/aslms",
    "mkdir -p data infra/proxy/certs",
    "echo \"UUID=$(sudo blkid -s UUID -o value /dev/<disk B>) /srv/aslms/data xfs defaults,noatime 0 0\" | sudo tee -a /etc/fstab",
    "sudo systemctl daemon-reload && sudo mount -a && df -h /srv/aslms/data",
    "mkdir -p data/store",
    "sudo chown -R 10001:10001 data infra/proxy/certs /mnt/aslms-backups",
    "sudo restorecon -R data infra/proxy/certs",
  ]));
  add(P("The document store must be writable by uid 10001, or `init` stops with the store-check message."));

  add(H2("5.3 Creating .env"));
  add(P("All settings come from `/srv/aslms/.env`, created from `.env.example`. `.env` holds secrets: never print it, never copy it into a ticket or e-mail, never commit it."));
  add(code(["cd /srv/aslms && cp .env.example .env && chmod 600 .env"]));
  add(P("Generate each secret separately with `openssl rand -hex 32` (the runbook's method); every value must be different. Hex is required: several values may contain only letters, digits, `_` or `-`, and the Redis password goes into a URL unencoded. The loop writes them straight into `.env` so they never appear on screen:"));
  add(code([
    "cd /srv/aslms",
    "for v in POSTGRES_PASSWORD ASLMS_APP_PASSWORD ASLMS_READONLY_PASSWORD REDIS_PASSWORD \\",
    "         ASLMS_JWT_SECRET GRAFANA_ADMIN_PASSWORD; do",
    "  sed -i \"s|^$v=.*|$v=$(openssl rand -hex 32)|\" .env",
    "done",
    "sed -i \"s|^FLOWER_BASIC_AUTH=.*|FLOWER_BASIC_AUTH=ops:$(openssl rand -hex 32)|\" .env",
    "grep -cE '^(POSTGRES_PASSWORD|ASLMS_APP_PASSWORD|ASLMS_READONLY_PASSWORD|REDIS_PASSWORD|ASLMS_JWT_SECRET|GRAFANA_ADMIN_PASSWORD|FLOWER_BASIC_AUTH)=.+' .env   # 7",
  ]));
  add(P("Then set the remaining values with an editor:"));
  add(table(["Variable", "Set to", "Notes"], [
    ["`APP_ENV`", "`prod`", "Exactly, lower case; any other value stops every service. Strict preflight, JSON logs, no console mail, no API documentation."],
    ["`COMPOSE_FILE`", "`compose.yml`", "Never `compose.dev.yml`. Add `compose.clamav-mirror.yml` or `compose.clamav-offline.yml` (separated by `:`) on a closed network."],
    ["`COMPOSE_PATH_SEPARATOR`", "`:`", "As in the example."],
    ["`COMPOSE_PROFILES`", "`monitoring` (or `monitoring,monitoring-host`)", "Preflight refuses a production stack without monitoring."],
    ["`PORTAL_BASE_URL`", "`https://<portal host name>`", "Section 3.4."],
    ["`ASLMS_SUPERADMIN_EMAIL`, `ASLMS_SUPERADMIN_PASSWORD`", "First Super Administrator's e-mail and a temporary password", "Section 5.8. 10+ characters with a letter and a digit; cleared after the first sign-in."],
    ["`MAIL_BACKEND`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_STARTTLS`, `SMTP_FROM`, `SMTP_FROM_NAME`", "The mail relay", "`MAIL_BACKEND=smtp` (or `auto`); `SMTP_FROM` on a verified domain."],
    ["`OPS_ALERT_EMAIL`", "Mailbox for monitoring alerts", "Design default: the Super Administrator's mailbox."],
    ["`NAPIX_CLIENT_ID`, `NAPIX_CLIENT_SECRET`, `NAPIX_DEPT_ID`, `NAPIX_AUTH_KEY`", "From the owner", "Secrets. Other `NAPIX_*` values as in the example unless the owner says otherwise."],
    ["`NAPIX_ENABLED`", "leave `false`", "Never `true` in any file (section 9.1)."],
    ["`BACKUP_DIR`", "`/mnt/aslms-backups`", "Outside the VM (section 8.1)."],
    ["`PG_SHARED_BUFFERS`, `PG_EFFECTIVE_CACHE_SIZE`", "As in section 2.2", "Defaults assume 8 GB."],
    ["`PROXY_BIND`, `PROXY_TRUSTED_UPSTREAM`", "Only if needed", "Section 3.2."],
    ["`COOKIE_SECURE`", "`true`", "Preflight refuses `false` in production."],
    ["`ASSISTANT_MODE`", "`off` at first", "`ollama` once Ollama and the model are ready (chapter 6)."],
  ], [3000, 2400, CW - 5400]));
  add(P("`DATABASE_URL_SYNC`, `ASLMS_MIGRATE_URL` and `REDIS_URL` in the example are for host-run development commands; Compose builds its own addresses from the passwords. Annexure B lists every variable group."));

  add(H2("5.4 The TLS certificate"));
  add(P("**From NIC or the data centre:** copy the certificate with its chain to `infra/proxy/certs/fullchain.pem` and the key to `infra/proxy/certs/privkey.pem`; `sudo chown 10001:10001 infra/proxy/certs/* && sudo restorecon -R infra/proxy/certs`."));
  add(P("**Internal CA:**"));
  add(code([
    "cd /srv/aslms",
    "docker compose run --rm --no-deps -v ./infra/proxy/certs:/certs init \\",
    "  aslms ops make-cert --host <portal host name> --ip <VM address> --out /certs",
  ]));
  add(B("Distribute `infra/proxy/certs/ca.crt` to every user PC as a trusted root (Windows: Install Certificate, Local Machine, \"Trusted Root Certification Authorities\"; or the department's desktop management)."));
  add(B("**Move `ca.key` off the VM** to safe offline storage, and remove it from the VM."));

  add(H2("5.5 The images"));
  add(P("The owner builds every image once on a connected build machine from the same commit as the release, saves them, and brings the archive in (runbook section 8). The runbook's example list names the core images; with the `monitoring` profile the monitoring images and the two other built images are needed too. The complete list from `compose.yml`:"));
  add(code([
    "# owner, on the build machine, in a checkout of the release, folder named aslms",
    "docker compose build && docker compose --profile ops build migrate && docker compose --profile monitoring build",
    "docker compose --profile monitoring pull",
    "docker save -o aslms-images.tar \\",
    "  postgres:16.15 redis:7.4.10-alpine nginx:1.28-alpine clamav/clamav:1.5.4 \\",
    "  aslms-init aslms-api aslms-worker aslms-scheduler aslms-web aslms-backup aslms-migrate \\",
    "  aslms-pgbouncer aslms-ops-exporter \\",
    "  prom/prometheus:v3.7.2 prom/alertmanager:v0.29.0 grafana/grafana:12.2.1 mher/flower:2.0.1 \\",
    "  quay.io/prometheuscommunity/postgres-exporter:v0.18.1 oliver006/redis_exporter:v1.78.0 \\",
    "  quay.io/prometheuscommunity/pgbouncer-exporter:v0.12.1",
    "# add prom/node-exporter:v1.10.2 and gcr.io/cadvisor/cadvisor:v0.52.1 for monitoring-host",
    "sha256sum aslms-images.tar > aslms-images.tar.sha256",
    "",
    "# administrator, on the pilot VM",
    "sha256sum -c aslms-images.tar.sha256 && docker load -i aslms-images.tar",
  ]));
  add(P("If the VM can reach the registries, the runbook's alternative is to build on the VM: `docker compose build` **and** `docker compose --profile ops build migrate` (a plain build skips the `migrate` image). Either way the code and the images must be the same release: `migrate` refuses (exit 5) an image built from other code (section 8.2)."));

  add(H2("5.6 The preflight check"));
  add(P("`aslms ops preflight` names any missing, short, default or repeated secret (the variable, never the value); with `APP_ENV=prod` an error stops the start. It runs as the first step of `init` on every start. Run it once by hand:"));
  add(code(["cd /srv/aslms", "docker compose run --rm --no-deps init aslms ops preflight", "# expected: preflight passed (APP_ENV=prod, N warning(s))"]));
  add(P("Fix every error in `.env`. A warning that `ASLMS_SUPERADMIN_PASSWORD` is set is expected until section 5.8 is finished."));

  add(H2("5.7 First start"));
  add(P("On a fresh, empty database `init` runs the preflight and the store check, migrates the database to the current version, sets the database role passwords and seeds the reference data; then every service starts. The first start is with court data **off**:"));
  add(code([
    "cd /srv/aslms",
    "NAPIX_ENABLED=false docker compose up -d --wait",
    "docker compose ps                 # every service running/healthy; init exited 0",
    "docker compose logs init          # preflight passed, store-check ... writable, seed",
  ]));
  add(P("ClamAV's first signature download takes several minutes; until then uploads answer 503 `scanner_unavailable`. If `init` stops, see section 9.9; if a container cannot read a mounted folder, `sudo ausearch -m avc -ts recent` (section 4.8). `init` migrates only an empty database; every later version is upgraded by the explicit `migrate` step (section 8.5)."));

  add(H2("5.8 The first Super Administrator"));
  add(P("With `ASLMS_SUPERADMIN_EMAIL` and `ASLMS_SUPERADMIN_PASSWORD` set, `init` (the seed) creates the first Super Administrator. Alternatively, on a system that has none (the password is prompted for, not echoed):"));
  add(code(["docker compose exec api aslms users create-super-admin --email <address>"]));
  add(steps([
    "The Super Administrator opens `https://<portal host name>/`, signs in with the e-mail and the temporary password, and enters the 6-digit code e-mailed to them.",
    "At the first sign-in the portal requires a new password and confirmation of the profile, including a mobile number.",
    "Remove the value of `ASLMS_SUPERADMIN_PASSWORD` from `.env` (preflight warns while it is set).",
    "Apply it, carrying the switch as it is now: `NAPIX_ENABLED=false docker compose up -d --wait`.",
  ]));
  add(P("Departments, offices, administrators and users are then set up in the portal's Administration screens (outside the scope of this guide)."));

  add(H2("5.9 Checks after the first start"));
  add(code([
    "cd /srv/aslms",
    "docker compose ps",
    "docker compose exec api aslms alerts test-mail --to <your address>      # mail relay delivers",
    "docker compose exec api aslms documents scan-check                     # ClamAV refuses the EICAR test file",
    "docker compose exec backup aslms ops backup                            # first backup, to the share outside the VM",
    "docker compose exec backup aslms ops restore-check                     # restore check passes",
    "docker compose exec api aslms system-health                            # the ASLMS service checks",
    "docker compose exec api aslms data-health                              # queue, jobs, mail, court-data health",
    "docker compose exec api aslms data-load status                         # the backdated load (empty at first)",
    "sudo ausearch -m avc -ts today                                         # no SELinux denials",
  ]));
  add(B("**From a user PC:** `https://<portal host name>/` loads with a trusted certificate; `http://` redirects; the address by IP is refused."));
  add(B("**System Health screen** (`/system`, Super Administrator): the ASLMS service cards are green; opening it makes no court call."));
  add(B("**Monitoring** (SSH tunnel, section 9.4): Grafana's \"ASLMS overview\" shows live figures; every Prometheus target is up."));
  add(B("**Ports:** from another machine only 443 and 80 answer (5432, 5433, 6379, 6432, 8000, 3000, 3310 and 11434 closed)."));

  add(H2("5.10 Turning on court data and the backdated collection"));
  add(P("When the checks pass and the owner authorises it, turn court data on. This recreates `api` and `worker` with the switch; every later `up` must carry it:"));
  add(code(["cd /srv/aslms", "{ON} docker compose up -d --wait"]));
  add(P("The daily cycle then runs by itself (section 9.6). The database starts empty and fills only from the court's data, user searches and department discovery. To collect the past, the Super Administrator starts the backdated collection on the Data Collection screen (Automatic Collection, Load Control), or by command with the start date the owner chooses (the development system loads from 1 January 2025):"));
  add(code([
    "docker compose exec api aslms data-load start --from <YYYY-MM-DD> --to <yesterday, YYYY-MM-DD>",
    "docker compose exec api aslms data-load status",
    "docker compose exec api aslms data-load pause --reason \"<why>\"     # and: aslms data-load resume",
  ]));
  add(P("The gateway allows about 1,000 calls per one-hour quota window and ASLMS keeps a reserve for the daily cycle and people's searches, so a long history takes days to weeks. Pause and resume from the screen or the command; do not stop the worker for that. Before go-live, complete section 10.2."));
}

// ===== 6 =====
function s6() {
  add(H1("6. The Case Assistant on the pilot VM"));
  add(H2("6.1 What runs, and the rules"));
  add(P("SourceTrace remains the intended AI (not available yet). Until it is, the Case Assistant may be answered by a local model served by **Ollama**, with `ASSISTANT_MODE=ollama`: on the pilot VM itself (the ASLMS host) or on a server the Government controls, reached by ASLMS over HTTP only at the address in `ASSISTANT_OLLAMA_URL`, so no court text leaves Government infrastructure. ASLMS keeps the search and the citation checks; the model only writes the answer from the numbered sources it is given. No model, model runtime or model library runs inside ASLMS's own processes (the preflight check `no_local_model`): Ollama runs on the host (or, optionally, as its own container, section 6.4) or on that Government server."));
  add(P("By default the model reads court information only: court orders, the court filings the officer may open, and case details and hearings. On a case's Assistant tab an officer may press \"Include This Case's Internal Records\"; from then on, in that conversation only, the model also reads that case's saved notes, file movement with remarks, pending actions and department documents that the officer may open on the case page. Drafts and other cases' records are never read, and the switch is recorded in the audit log (`assistant.internal_included`). SourceTrace never receives notes or internal documents."));
  add(RULE("Rules for the local model", [
    "**Never a cloud model.** A model name or tag containing `cloud`, an address on ollama.com, or an address carrying user information or a query is refused by the preflight (`no_cloud_model`, fatal at every `APP_ENV`).",
    "**Never run `ollama signin`** and **never set `OLLAMA_DEBUG`** (it logs prompts, which can hold a case's notes and remarks).",
    "**Never open 11434 in the firewall.** In production `aslms ops preflight` refuses a model address that resolves outside loopback, private (RFC 1918, fc00::/7) or link-local addresses.",
  ]));

  add(H2("6.2 NVIDIA driver (if the VM has a GPU)"));
  add(P("From **NVIDIA's official CUDA repository for RHEL 9**, following NVIDIA's driver installation guide (Rocky 9 and AlmaLinux 9 use the same repository). " + VENDOR + " Depending on the driver generation, NVIDIA's guide installs the open kernel modules (`nvidia-open`, or the module stream `nvidia-driver:open-dkms`) or the proprietary ones (`nvidia-driver:latest-dkms`)."));
  add(code([
    "sudo dnf install -y epel-release                     # RHEL 9: the EPEL release package from Fedora",
    "sudo dnf config-manager --set-enabled crb            # RHEL 9: codeready-builder-for-rhel-9-x86_64-rpms",
    "sudo dnf install -y kernel-devel-matched kernel-headers dkms",
    "sudo dnf config-manager --add-repo https://developer.download.nvidia.com/compute/cuda/repos/rhel9/x86_64/cuda-rhel9.repo",
    "sudo dnf clean expire-cache",
    "sudo dnf install -y nvidia-open                      # or: sudo dnf module install -y nvidia-driver:open-dkms",
    "sudo reboot",
    "nvidia-smi                                           # the GPU, the driver version and its memory",
  ]));
  add(P("With Secure Boot on, the DKMS module must be signed with an enrolled key (NVIDIA's guide; agree the policy with the data centre). SELinux stays enforcing."));

  add(H2("6.3 Install Ollama"));
  add(P("Ollama 0.40 or later, with Ollama's official Linux installer (it installs the `ollama` command and a systemd service running as the `ollama` user). To pin a version (the exact version is confirmed in the owner's live check on the pilot machine, backlog row 195):"));
  add(code(["curl -fsSL https://ollama.com/install.sh | OLLAMA_VERSION=<version 0.40 or later> sh", "ollama --version && systemctl status ollama"]));

  add(H2("6.4 Where Ollama listens on the same VM"));
  add(table(["Choice", "Settings", "Notes"], [
    ["**A. The VM's private address under an internal name** (recommended: ready to scale)", "Ollama: `OLLAMA_HOST=<VM private address>:11434`. ASLMS: `ASSISTANT_OLLAMA_URL=http://ai.aslms.internal:11434`, with a DNS record pointing to the VM.", "Not opened in the firewall, so only the VM's own containers reach it. Moving the model to a GPU server later changes only the DNS record (chapter 16)."],
    ["B. The design's default", "Ollama: `OLLAMA_HOST=172.17.0.1:11434` (the Docker bridge, as the runbook says for Linux). ASLMS: the default `ASSISTANT_OLLAMA_URL=http://host.docker.internal:11434` (`extra_hosts` on `api` and `init`).", "Never `0.0.0.0` on a host with a public address."],
    ["C. Ollama as a Compose service", "Profile `ollama` with `ASSISTANT_OLLAMA_URL=http://ollama:11434`; on a GPU add `compose.ollama-gpu.yml` to `COMPOSE_FILE` (needs the NVIDIA Container Toolkit).", "Optional in the design; no published port; model pulled with `docker compose exec ollama ollama pull qwen3.5:4b`."],
  ], [2700, 3900, CW - 6600]));
  add(P("Ollama may instead run on **a separate server the Government controls** (for example a GPU server at the data centre): it then listens on the private network only, with the firewall open to the ASLMS host only, and `ASSISTANT_OLLAMA_URL` names that server (chapter 13 for the full layout)."));
  add(P("For choice A or B, set the listening address and the keep-alive and parallel settings (parallel must equal `ASSISTANT_OLLAMA_SLOTS`, default 1):"));
  add(code([
    "sudo systemctl edit ollama",
    "[Service]",
    "Environment=\"OLLAMA_HOST=<VM private address>:11434\"",
    "Environment=\"OLLAMA_KEEP_ALIVE=-1\"",
    "Environment=\"OLLAMA_NUM_PARALLEL=1\"",
    "# then:",
    "sudo systemctl daemon-reload && sudo systemctl restart ollama && sudo systemctl enable ollama",
  ]));
  add(P("Traffic from the containers to the host arrives through Docker's bridge interfaces, which Docker places in firewalld's `docker` zone; the public zones keep 11434 closed. Check from inside the `api` container in section 6.5."));

  add(H2("6.5 Pull the model and test it"));
  add(code([
    "export OLLAMA_HOST=<VM private address>:11434",
    "ollama pull qwen3.5:4b                                 # or the model named in ASSISTANT_OLLAMA_MODEL",
    "ollama list",
    "curl -s http://<VM private address>:11434/api/chat -d '{\"model\":\"qwen3.5:4b\",\"stream\":false,\"think\":false,",
    "  \"keep_alive\":-1,\"messages\":[{\"role\":\"user\",\"content\":\"Reply with the single word: ready\"}]}'",
    "curl -s http://<VM private address>:11434/api/ps      # size_vram equal to size: fully on the GPU",
    "# from inside the api container (after the stack is running):",
    "docker compose exec api python -c \"import urllib.request;print(urllib.request.urlopen('http://ai.aslms.internal:11434/api/version').read())\"",
  ]));
  add(P("Pulling a model downloads it from Ollama's model library (outbound HTTPS during installation, or the model files copied in); it is not a sign-in. The first call loads the model (up to about two minutes)."));

  add(H2("6.6 Point ASLMS at the model"));
  add(table(["Variable (`.env`)", "Value", "Meaning"], [
    ["`ASSISTANT_MODE`", "`ollama` (default `off`)", "off / preview / sourcetrace / ollama; `ollama` is allowed in production, preview is refused there"],
    ["`ASSISTANT_OLLAMA_URL`", "`http://ai.aslms.internal:11434` (choice A); default `http://host.docker.internal:11434` (choice B); `http://ollama:11434` (choice C)", "Loopback, private or link-local in production; no API key or secret"],
    ["`ASSISTANT_OLLAMA_MODEL`", "`qwen3.5:4b`", "Any Ollama model held locally; never a cloud model"],
    ["`ASSISTANT_OLLAMA_KEEP_ALIVE`", "`-1`", "Keeps the model loaded"],
    ["`ASSISTANT_OLLAMA_SLOTS`", "`1`", "Questions answered at once; equal to `OLLAMA_NUM_PARALLEL`"],
    ["`ASSISTANT_OLLAMA_TIMEOUT_SECONDS`, `ASSISTANT_TIMEOUT_SECONDS`", "`30`, `45`", "The model's share and the whole question's limit"],
    ["`ASSISTANT_OLLAMA_SLOT_WAIT_SECONDS`", "`20`", "How long a question waits for the busy slot"],
    ["`ASSISTANT_OLLAMA_NUM_CTX`, `ASSISTANT_OLLAMA_NUM_PREDICT`", "`16384`, `800`", "The model's context and the longest answer"],
    ["`ASSISTANT_OLLAMA_SOURCES`, `ASSISTANT_OLLAMA_SOURCE_CHARS`", "`6`, `4000`", "Sources given per question and their length"],
    ["`ASSISTANT_OLLAMA_HISTORY_TURNS`", "`2`", "Earlier questions of the conversation given as context"],
    ["`ASSISTANT_OLLAMA_INTERNAL_CHARS`", "`12000`", "Internal records given after the switch; `0` sends none"],
    ["`ASSISTANT_OLLAMA_HEARINGS`", "`10`", "Hearings given with the case details"],
  ], [3300, 3000, CW - 6300]));
  add(code([
    "cd /srv/aslms",
    "NAPIX_ENABLED=<true or false, as now> docker compose up -d --wait      # recreates api with the new settings",
    "docker compose exec api aslms assistant warm && docker compose exec api aslms assistant status",
  ]));
  add(P("`aslms assistant warm` loads the model now and keeps it loaded (it waits up to 300 seconds); `aslms assistant status` shows the mode, the state and the last 24 hours' conversations and questions; `aslms assistant check` prints the Case Assistant's consistency counts, each of which must be 0 (exit 1 otherwise). `aslms assistant ask` and `aslms assistant include-internal` are for development and test and refuse to run with `APP_ENV=prod`."));
  add(P("The api also starts a load in the background when it starts, and opening the Assistant starts one when the model is held but not loaded. System Health then shows a \"Case Assistant Model\" card (version, model, loaded, on GPU, kept loaded until; never the address). Questions during a model load answer 503 `assistant_loading` (about two minutes on a first load); when the single slot is busy, 503 `assistant_busy`."));

  add(H2("6.7 Without a GPU"));
  add(P("On the CPU a 4B model takes roughly 30–90 seconds per answer, longer than the default model limit of 30 seconds, so questions fail with \"No answer came within …\" unless the limits are raised. Options:"));
  add(REC([
    "Raise `ASSISTANT_OLLAMA_TIMEOUT_SECONDS` (at most 280) and `ASSISTANT_TIMEOUT_SECONDS` (at most 300) together, keeping both below the portal relay's `RELAY_TIMEOUT_SECONDS` (default 120), for example 100 and 110.",
    "Or use a smaller model (for example `qwen3.5:2b`): faster, less accurate.",
    "Or leave the Case Assistant off until a GPU or SourceTrace is available (preview mode is refused in production).",
  ]));

  add(H2("6.8 Changing the model, switching off, SourceTrace later"));
  add(B("**Change the model:** pull it, set `ASSISTANT_OLLAMA_MODEL`, recreate the API carrying the switch, then `aslms assistant warm`."));
  add(B("**Switch off:** `ASSISTANT_MODE=off` and recreate the API the same way; stored local-model answers stay readable (the migration 0032 downgrade refuses while any exists)."));
  add(B("**SourceTrace later** (row 36): `ASSISTANT_MODE=sourcetrace` with the `SOURCETRACE_*` settings. SourceTrace receives court orders and court filings only, never notes or internal documents."));
}

// ===== 7 =====
function s7() {
  add(H1("7. The one-VM installer (aslms-setup)"));
  add(LATER("Planned: backlog row 193 `vm-installer`, round 1 (not yet built)", [
    "The owner has asked for an installer for the one VM as well as the manual steps. This chapter describes it as planned; **it will be updated when the installer is built**. Until then, use chapters 4 to 6 and section 8.5, which remain the reference. The multi-VM roles and the `move` commands are round 2 (row 194, chapter 15).",
  ]));
  add(H2("7.1 What it will be"));
  add(P("One program, `aslms-setup`, run with administrator rights on the pilot VM. It targets **Rocky Linux 9 and RHEL 9** (AlmaLinux 9 alike). Its **`all-in-one`** role installs the whole stack on one VM: the same steps as chapters 4 to 6, in the same order, asking only for what it cannot decide itself. It is planned to be safe to run again (it continues where it stopped), to log every step, and never to print a secret."));
  add(code([
    "sudo ./aslms-setup                         # install: choose the all-in-one role",
    "sudo aslms-setup check                     # re-check the running system",
    "sudo aslms-setup upgrade <update file>     # apply an update (section 8.3)",
    "sudo aslms-setup rollback                  # after a failed update with a database change (section 8.6)",
  ]));
  add(H2("7.2 The installer's steps"));
  add(table(["#", "Installer step", "What it does", "What the administrator answers or prepares", "Manual equivalent"], [
    ["1", "VM checks", "Checks the OS (Rocky / RHEL 9), CPU, memory, disks, GPU, time sync, reach of the court-data gateway and the mail relay", "VM as in section 2.2; outbound rules of chapter 3", "Does sections 2.2, 3.3 and 4.4 for you"],
    ["2", "Base system", "Removes Podman and Buildah; installs Docker with the Compose plugin; SELinux labels; firewalld (only HTTPS published); data disks; log rotation", "Which disks are disk A and disk B; the admin and users' networks", "Does sections 4.5 to 4.9 for you"],
    ["3", "Host performance settings", "tuned profile, low swappiness, transparent huge pages off, open-file limit; checks XFS ftype=1", "Nothing (fast SSD is the data centre's part)", "Does section 4.10 for you"],
    ["4", "Ready to scale", "Uses the internal name for the AI service, keeps the database and documents on their own disks, checks the internal names resolve", "The DNS records of section 2.5", "Does section 2.5 for you"],
    ["5", "Backups off the VM", "Mounts the backup share and checks uid 10001 can write to it", "The share's address and options", "Does sections 4.5 and 8.1 for you"],
    ["6", "Questions", "Asks for the portal host name, the mail relay and the certificate", "Host name and DNS; relay address, port, user, sender; NIC / data-centre certificate or internal CA", "Does sections 3.4, 3.5, 5.3 and 5.4 for you"],
    ["7", "Secrets and .env", "Generates every secret without showing it, writes `.env`, runs `aslms ops preflight`", "The court-data credentials and the Super Administrator's e-mail, typed in when asked", "Does sections 5.3 and 5.6 for you"],
    ["8", "Images and database", "Verifies and loads the release's images, runs the `migrate` step and `init`", "The release file", "Does sections 5.1, 5.5 and 5.7 for you"],
    ["9", "Start", "Starts the stack with `NAPIX_ENABLED` given only on the command line, never written to a file", "Whether court data is switched on now (the owner's decision)", "Does sections 5.7 and 5.10 for you"],
    ["10", "First Super Administrator", "Creates the first Super Administrator", "The e-mail; they complete the first sign-in", "Does section 5.8 for you"],
    ["11", "Case Assistant on the VM", "With a GPU: the NVIDIA driver, Ollama on the private address under the internal name, the model pulled and tested; never a cloud model, never `ollama signin`. Without a GPU: the CPU, a smaller model, or off", "The choice; a reboot for the driver", "Does chapter 6 for you"],
    ["12", "Final checks", "Checks the portal page and System Health", "Open the portal from a user PC", "Does section 5.9 for you"],
  ], [400, 1500, 2800, 2600, CW - 7300]));
  add(H2("7.3 Check, upgrade and rollback; re-runs and the log"));
  add(B("**`check`** re-checks the running system (the checks of sections 5.9 and 9.7)."));
  add(B("**`upgrade <update file>`** applies an update by itself: signature, pre-checks, backup, only the changed parts, the stop / migrate / start order when needed, the switch on the command line, checks, automatic rollback where possible (section 8.3)."));
  add(B("**`rollback`** restores the `pre-migrate` backup and starts the previous release's images, on the administrator's yes (section 8.6)."));
  add(B("**Re-running** is safe: the installer continues where it stopped. **The log:** every step is logged and no secret printed; where it is kept will be fixed by the row 193 design (Annexure D)."));
  add(B("**VMs without internet:** an offline bundle with the operating-system packages and the images (manual equivalent: the data centre's mirrors, `docker load`, ClamAV's mirror or offline mode)."));
}

// ===== 8 =====
function s8() {
  add(H1("8. Backups and updates for the pilot"));
  add(H2("8.1 Backups off the VM, and snapshots"));
  add(P("With one VM there is no standby: the backups are the only way back. The `backup` service writes a backup at minute 30 of every `BACKUP_INTERVAL_HOURS` hours, IST (00:30, 06:30, 12:30 and 18:30 by default) into `BACKUP_DIR`, which **must be storage outside the VM**:"));
  add(B("`db/aslms-<date-time>[-tag].dump` (the whole database), `db/roles-<…>.sql` (roles with password hashes: **keep it as secret as `.env`**), `db/manifest-<…>.json` (revision, sizes, checksums, row counts);"));
  add(B("`store/`: an add-only mirror of the document store; `status/`: last backup, last success, last restore check."));
  add(P("Retention prunes dump sets only, never the store mirror: everything from the last 48 hours, the first set of each day for 14 days, each Sunday for 8 weeks, each 1st of the month for 12 months, and the last 5 `pre-migrate` sets (`BACKUP_KEEP_*`). The restore check runs every Sunday at 04:30 IST. Worst-case loss: about 6 hours of work."));
  add(code([
    "docker compose exec backup aslms ops backup [--tag before-something]",
    "docker compose exec backup aslms ops backup-status",
    "docker compose exec backup aslms ops restore-check",
  ]));
  add(REC([
    "`BACKUP_DIR` on a backup share (or a folder the data centre's backup service collects); the data centre copies it off-site at least weekly, encrypted.",
    "**VM snapshots** before every update and every operating-system change, and on a regular schedule agreed with the data centre. A snapshot complements the backups; it does not replace them (a snapshot taken while the database writes may need PostgreSQL's recovery on start).",
    "Keep `.env` and `ca.key` in secure custody, separately from the backups. Disaster restore: section 9.3.",
  ]));

  add(H2("8.2 Releases: patch and feature, and how they are delivered"));
  add(P("The owner develops and tests each change on the development machine first, then the data centre applies it. Today the runbook's procedure is used (section 8.5). Numbered releases and signed update files are planned (row 192)."));
  add(REC([
    "**Patch releases** (for example v1.4.1) carry fixes and only the images that changed; most need no database change. **Feature releases** (for example v1.5.0) carry new functions and may carry migrations.",
    "Every release has **release notes**: changes; new or changed settings (new lines of `.env.example`); migrations (so whether a maintenance window is needed); one-off steps (for example \"everyone signs in again\", which the session-timeout change of row 169 needs).",
    "**Built once:** images are built once from the release tag outside the data centre and never rebuilt or edited on the VM. **Delivered as one file** (for example `aslms-1.4.1.update`: the changed images saved with `docker save`, the Compose files, the `.env.example` changes, a checksum list, signed by the owner), brought in through the approved route. A pull from an approved private registry is an option only if the data centre allows it.",
    "Keep the previous release's file and images (about 30 GB) until the new release has run cleanly for a few days.",
  ]));
  add(NOTE("Existing guard: `migrate` refuses an image built from other code", [
    "Runbook section 6 (design followups-oct, decision 26): `aslms ops migrate` compares the code in its image with `./backend` (mounted read-only) and stops with **exit 5** (\"this image was built from other code than ./backend\") before any backup or connection; there is no override. With images loaded by `docker load` and no source tree, it prints \"migrate: no source tree to compare\" and continues. The code folder and the images must always come from the same release.",
  ]));

  add(H2("8.3 Updating the pilot in two steps (planned, rows 192 and 193)"));
  add(LATER("Planned: patch updates with one file and one command", [
    "**Step 1.** Receive one signed update file, for example `aslms-1.4.1.update`, through the approved route.",
    "**Step 2.** In the window, run `sudo aslms-setup upgrade <file>` on the pilot VM.",
    "Until the installer exists, use the manual procedure of section 8.5.",
  ]));
  add(P("What the command will do by itself:"));
  add(steps([
    "**Verify** the file's signature and checksums; refuse a file that fails.",
    "**Pre-checks:** free disk, every service healthy, the backup storage reachable.",
    "**Backup** before any change (the `migrate` step adds its own `pre-migrate` backup when the database changes).",
    "**Apply only what changed** (table below).",
    "**Start** with the court-data switch given on the command line, as it was before.",
    "**Checks:** the portal page, System Health, `aslms data-load status`.",
    "**Rollback:** with no database change, a failed check rolls back automatically to the previous images. After a database change, a failed migration undoes itself (migrations run in a transaction); a failed check afterwards stops and offers `aslms-setup rollback` (restore the `pre-migrate` backup and the previous images), run on the administrator's yes.",
  ]));
  add(table(["Kind of update", "What the command does", "Downtime (expected)"], [
    ["Portal-only patch", "Replaces the portal (`web`) image; no database step", "Seconds"],
    ["Backend patch without a migration", "Replaces the backend images, restarts `api` and `worker`", "About a minute"],
    ["Release with a migration", "Stop `api`, `worker`, `scheduler`, `web`, `pgbouncer`; `migrate`; start", "10–20 minutes, planned window"],
  ], [2600, 4600, CW - 7200]));

  add(H2("8.4 The maintenance window"));
  add(P("Keep away from the scheduled runs (IST, from `backend/aslms/jobs/celery_app.py` and the backup service): cause lists **06:30 and 18:30**, status refresh **20:00**, masters 06:00, digests 08:00, disposed refresh 02:30, dedupe 03:00, call-log purge 03:45, weekly sweep **Sunday 02:00**, discovery Saturday 02:00, backups 00:30 / 06:30 / 12:30 / 18:30, restore check **Sunday 04:30**."));
  add(REC([
    "Releases with a migration, and reboots: about **21:00–23:00 on a weekday** (the 18:30 and 20:00 work is queued in the database and resumes after the start) or a **Sunday morning after 09:00**. Expected downtime 10–20 minutes.",
    "Patches without a database change at any quiet time. Notify users in advance; silence alerts in Alertmanager for the window; take a VM snapshot first.",
  ]));

  add(H2("8.5 Updating today: the manual procedure"));
  add(RULE("Upgrade order: load (or build), stop, migrate, start", ["`docker compose up` never migrates an existing database: when a build needs a newer schema, `init` exits with code 3 and nothing else starts. Never downgrade by hand."]));
  add(steps([
    "Read the release notes. Notify users; silence alerts; take a VM snapshot.",
    "Manual backup: `docker compose exec backup aslms ops backup --tag before-<release>`.",
    "New code: unpack the release into `/srv/aslms` (keeping `.env` and `data`); add any new `.env` lines named in the release notes.",
    "Images: `sha256sum -c` and `docker load -i <images file>` (or, building on the VM, `docker compose build` **and** `docker compose --profile ops build migrate`).",
    "Stop: `docker compose stop api worker scheduler web pgbouncer`.",
    "Migrate: `docker compose --profile ops run --rm migrate` (preflight; refuses while an application session is connected; writes and verifies a `pre-migrate` backup; upgrades; seeds; writes an audit row).",
    "Start with the switch as before: `{ON} docker compose up -d --wait` (or `NAPIX_ENABLED=false` if court data was off).",
    "Checks: the portal page, System Health, `docker compose exec api aslms data-load status`, section 10.3; any one-off step from the release notes.",
  ]));
  add(table(["Exit / message", "Meaning", "Action"], [
    ["`init` exits 3, \"database behind head\"", "An upgrade is needed", "Steps 5 to 7"],
    ["`init` exits 4, \"database newer than this build\"", "The code is older than the database", "Deploy the matching release"],
    ["`migrate` exits 5, \"built from other code than ./backend\"", "Code and images from different releases", "Put matching code and images in place (steps 3 and 4), migrate again"],
  ], [3600, 2700, CW - 6300]));

  add(H2("8.6 Rollback"));
  add(P("Migrations go forward only, and some refuse a downgrade (a reference-data migration writes append-only audit rows). A rollback is therefore **the `pre-migrate` backup restored plus the previous release's images**, never `alembic downgrade`:"));
  add(steps([
    "Put the previous release's code back in `/srv/aslms` and load its images.",
    "Stop: `docker compose stop api worker scheduler web pgbouncer backup`.",
    "Restore: `docker compose --profile ops run --rm migrate aslms ops restore --dump /backups/db/aslms-<…>-pre-migrate.dump --roles /backups/db/roles-<…>.sql --confirm-overwrite aslms --store-from /backups/store`.",
    "Start with the switch as before; run the checks.",
  ]));
  add(P("Without a database change, a rollback is only the previous code and images and a start. Work done between the update and a restore is lost, so decide quickly. A VM snapshot taken before the update is a further fallback."));

  add(H2("8.7 Without staging: reducing the risk"));
  add(REC([
    "Test every release with a database change on the owner's development machine against a recent copy of the data shape, and time its migration there.",
    "Apply such releases only in a window, with a snapshot and a manual backup, and with the previous release at hand.",
    "Do not run a second ASLMS on the pilot VM as \"staging\": it would share the court-data allowance, the mail relay and the resources. A staging VM comes with Part 2.",
  ]));
}

// ===== 9 =====
function s9() {
  add(H1("9. Operating ASLMS"));
  add(P("This chapter applies to the pilot VM and, later, to every VM of Part 2."));
  add(H2("9.1 Starting, stopping, the switch, and reboots"));
  add(RULE("The court-data switch", [
    "`NAPIX_ENABLED` is set only on the command line, never in `.env`, `compose.yml` or any other file. Compose passes it to the `worker` and the `api`. **Every `docker compose up` that creates or recreates a service, even a single one, must carry it**, or that service comes back with court data off.",
  ]));
  add(table(["Task", "Command (in /srv/aslms)"], [
    ["Start or apply `.env` changes, court data on", "`{ON} docker compose up -d --wait`"],
    ["The same, court data off", "`NAPIX_ENABLED=false docker compose up -d --wait`"],
    ["Recreate one service", "`NAPIX_ENABLED=<as now> docker compose up -d <service>`"],
    ["Restart a service without recreating it (keeps its switch)", "`docker compose restart <service>`"],
    ["Stop everything / see the state", "`docker compose stop` / `docker compose ps`"],
    ["What the worker sees for the switch", "`docker compose exec worker printenv NAPIX_ENABLED` (also the ops exporter's `aslms_napix_switch_on`)"],
  ], [4000, CW - 4000]));
  add(P("**After a VM reboot:** Docker starts at boot and restarts the containers (`restart: unless-stopped`) as they were created, so the switch stays as it was at the last `up`; `init` does not run again. Check `docker compose ps`; if a service is not healthy, `NAPIX_ENABLED=<as before> docker compose up -d --wait`. Jobs interrupted by the restart are marked `interrupted` when the worker, scheduler and backup start; never run `aslms queue-run` by hand during a restart. To pause only the backdated collection, use the Data Collection screen or `aslms data-load pause`."));

  add(H2("9.2 Backups"));
  add(P("Section 8.1."));

  add(H2("9.3 Restore check and disaster restore"));
  add(P("**Restore check:** Sunday 04:30 IST, the latest dump is restored into a scratch database, revision and row counts compared, 50 random documents checked against the store mirror, the scratch database dropped. By hand: `docker compose exec backup aslms ops restore-check [--dump <file>]`."));
  add(P("**Disaster restore** (a new or wiped VM):"));
  add(steps([
    "Prepare the VM (chapter 4) and the application folder (sections 5.1 to 5.5) with the **same `.env` secrets** and the same release as the backup. Do not start the stack.",
    "Start only the database: `docker compose up -d postgres`.",
    "Make sure nothing else runs: `docker compose stop api worker scheduler web pgbouncer backup`.",
    "Restore: `docker compose --profile ops run --rm migrate aslms ops restore --dump /backups/db/aslms-<…>.dump --roles /backups/db/roles-<…>.sql --confirm-overwrite aslms --store-from /backups/store`",
    "Start with the switch as before: `NAPIX_ENABLED=<as before> docker compose up -d --wait`.",
    "Check: the Super Administrator signs in; `docker compose exec api aslms ops load-report` matches the manifest; the data-health screen loads.",
  ]));
  add(P("Rehearse it once (for example on a temporary VM) and record the time from empty to signed in."));

  add(H2("9.4 Monitoring"));
  add(P("With `COMPOSE_PROFILES=monitoring`, Prometheus scrapes every 30 seconds and keeps 30 days, Alertmanager mails alerts to `OPS_ALERT_EMAIL` through the `SMTP_*` relay, and Grafana shows \"ASLMS overview\", \"PostgreSQL\" and \"Redis and Celery\". The screens listen on 127.0.0.1 only; open them through an SSH tunnel:"));
  add(code(["ssh -L 3001:127.0.0.1:3001 -L 9090:127.0.0.1:9090 -L 9093:127.0.0.1:9093 -L 5555:127.0.0.1:5555 <admin>@<VM>"]));
  add(table(["Screen", "Address (through the tunnel)", "Sign-in"], [
    ["Grafana", "`http://127.0.0.1:3001`", "`admin` / `GRAFANA_ADMIN_PASSWORD`"],
    ["Prometheus", "`http://127.0.0.1:9090`", "none (loopback only)"],
    ["Alertmanager", "`http://127.0.0.1:9093`", "none (loopback only)"],
    ["Flower", "`http://127.0.0.1:5555`", "`FLOWER_BASIC_AUTH`"],
  ], [2000, 3600, CW - 5600]));
  add(P("Test the alert path once: `docker compose stop clamav`; within about 10 minutes ClamAVDown fires and the e-mail arrives; then `NAPIX_ENABLED=<as now> docker compose up -d clamav`. Silence alerts during planned work with Alertmanager's \"New silence\"."));
  add(table(["Alert", "First action (runbook section 17)"], [
    ["ServiceDown", "`docker compose ps`, `docker compose logs <service>`; `up -d` with the switch. If `postgres` is down, check disk space first."],
    ["PortalDown", "Check `proxy`, `web`, `api`; `docker compose logs proxy` names a missing certificate."],
    ["RedisDown", "`docker compose logs redis`; restart it (nothing durable is lost)."],
    ["ClamAVDown / ClamAVSignaturesOld", "`docker compose logs clamav`; check the signature source."],
    ["PostgresConnectionsHigh", "Find the stuck client in `pg_stat_activity` before raising `PG_MAX_CONNECTIONS`."],
    ["PgBouncerClientsWaiting", "`SHOW POOLS`; long transactions; raise `PGBOUNCER_DEFAULT_POOL_SIZE` only after finding the cause."],
    ["CertExpiring", "Renew (section 5.4); `docker compose restart proxy`."],
    ["DiskLow", "`BACKUP_DIR`, the store, old images, `docker system df`. Never delete the store or its mirror."],
    ["WorkerStalled", "`docker compose logs worker`; `docker compose restart worker`."],
    ["JobStuck / JobLate", "`aslms ops repair-jobs --dry-run`; `docker compose logs scheduler`; Flower; the data-health screen."],
    ["BackupMissing / RestoreCheckMissing", "`docker compose logs backup`; `aslms ops backup-status`; run by hand once fixed."],
    ["NapixErrorsHigh", "Data-health screen's court-data block; pause the load if the gateway fails. Never change the switch in a file."],
    ["MailFailing", "Sign-in codes may not arrive: `aslms alerts test-mail --to <address>`; check the relay."],
  ], [2800, CW - 2800]));
  add(P("**PgBouncer and the connection budget.** `api`, `worker` and `scheduler` reach PostgreSQL through PgBouncer (transaction mode, 6432, never published). The preflight checks `NAPIX_REQUEST_SLOTS` + 1 + 1 + `DB_APART_POOL_SIZE` + 4 ≤ `PGBOUNCER_DEFAULT_POOL_SIZE` (defaults 6 + 1 + 1 + 3 + 4 = 15 ≤ 20). Checks: `docker compose exec api psql -h pgbouncer -p 6432 -U aslms_readonly pgbouncer -c \"SHOW POOLS\"` (asks for `ASLMS_READONLY_PASSWORD`) and `docker compose exec api aslms ops pool-check --holders 8 --pages 20 --apart 200 --seconds 30`."));

  add(H2("9.5 Logs"));
  add(code([
    "docker compose logs --tail 200 <service>          # init, api, worker, scheduler, backup, proxy, clamav ...",
    "docker compose logs -f --tail 50 worker",
    "sudo ausearch -m avc -ts recent                    # SELinux denials",
  ]));
  add(P("With `APP_ENV=prod` the application logs are JSON, rotated at 20 MB × 5. Secrets never appear in logs. PostgreSQL logs statements slower than 2 seconds and lock waits."));

  add(H2("9.6 Scheduled jobs"));
  add(table(["When (IST)", "Job"], [
    ["06:00 daily", "Court master data"],
    ["06:30 and 18:30 daily", "Cause lists (18:30 also re-checks corrected lists)"],
    ["20:00 daily", "Current status of held cases"],
    ["02:30 / 03:00 / 03:45 daily", "Disposed-case refresh / duplicate-case sweep / court-call log purge (older than 2 years)"],
    ["08:00 daily", "Daily e-mail digests"],
    ["Sunday 02:00 / Saturday 02:00", "Weekly sweep of cases not fully fetched / department discovery"],
    ["Every 2 minutes", "E-mail notifications; storing search results"],
    ["Every 5 minutes", "Alert event scan; text extraction; next dates from orders; SourceTrace ingestion (sends nothing until a connector exists)"],
    ["Every 15 minutes / hourly at :10", "Rescoring after rule changes / alert date sweep"],
    ["Every 6 hours at :30; Sunday 04:30", "Backup; restore check (`backup` service)"],
  ], [3200, CW - 3200]));

  add(H2("9.7 Routine checks"));
  add(table(["How often", "Check"], [
    ["Daily", "Grafana \"ASLMS overview\" and firing alerts; the data-health screen (queue, jobs, mail, last backup); `aslms ops backup-status`"],
    ["Weekly", "Restore check passed; free disk on the VM and on `BACKUP_DIR`; the off-site copy and the snapshots; no new SELinux denials"],
    ["Monthly", "Certificate expiry (`openssl x509 -enddate -noout -in infra/proxy/certs/fullchain.pem`); operating-system updates and an evening reboot if needed; old release images beyond the previous one removed"],
  ], [1600, CW - 1600]));

  add(H2("9.8 Secret rotation"));
  add(table(["Secret", "How (every `up -d` carries the switch)"], [
    ["`ASLMS_JWT_SECRET`", "Change in `.env`, `up -d`. Everyone is signed out."],
    ["`ASLMS_APP_PASSWORD`, `ASLMS_READONLY_PASSWORD`", "Change in `.env`, `up -d`; `init` applies it first."],
    ["`REDIS_PASSWORD`", "Change in `.env`, `up -d`. Redis restarts empty, which is safe."],
    ["`POSTGRES_PASSWORD`", "First `ALTER ROLE aslms PASSWORD '<new>'` in psql (runbook section 5), then `.env`, `up -d`."],
    ["Court-data credentials, mail secrets", "Change in `.env`, `up -d`."],
    ["`GRAFANA_ADMIN_PASSWORD`", "Change in `.env`, then `docker compose exec grafana grafana cli admin reset-admin-password '<new>'`."],
    ["`FLOWER_BASIC_AUTH`", "Change in `.env`, `up -d flower`."],
  ], [3600, CW - 3600]));

  add(H2("9.9 Common problems"));
  add(table(["Symptom", "Cause and action"], [
    ["`init` exits with a preflight error", "The message names the variable (never the value). Fix `.env`, start again."],
    ["`init` stops at the store check", "Store not writable by uid 10001: `sudo chown -R 10001:10001 ./data/store`, start again."],
    ["A container cannot read or write a mounted folder", "SELinux label: `sudo ausearch -m avc -ts recent`, relabel (section 4.8). Never disable SELinux."],
    ["`preflight fatal: libpq: ...` or `no_local_model`", "Wrong image; use the release's images."],
    ["Uploads answer 503", "ClamAV not ready: `docker compose ps clamav`, `docker compose logs clamav`."],
    ["Sign-in answers 429 `throttled`", "Many sign-ins from one address; if a whole office is refused each morning, raise `PROXY_SESSION_RATE` / `PROXY_SESSION_BURST` and restart the proxy."],
    ["Upload refused 413 `too_large`", "Over `UPLOAD_MAX_BYTES` (20 MB)."],
    ["No sign-in code arrives", "`aslms alerts test-mail --to <address>`; the MailFailing alert."],
    ["Portal refused, or sign-in fails with an origin error", "Opened by IP or another name; use exactly `PORTAL_BASE_URL`."],
    ["A job shows `running` for hours", "`aslms ops repair-jobs --dry-run`, then without `--dry-run`."],
    ["Disk full", "`BACKUP_DIR` (lower `BACKUP_KEEP_*`, never delete the store mirror), the store, old images, `docker system df`."],
    ["The proxy restarts", "`docker compose logs proxy`: a missing certificate file is named."],
    ["Court data stopped after a restart", "A service was recreated without the switch: `{ON} docker compose up -d --wait` (with the owner's authority)."],
    ["Case Assistant answers 503 or times out", "`aslms assistant status`; `systemctl status ollama`; on a CPU, section 6.7."],
  ], [3200, CW - 3200]));
}

// ===== 10 =====
function s10() {
  add(H1("10. Checklists for the pilot"));
  add(H2("10.1 Pre-deployment"));
  add(box([
    "Annexure D settled with the data centre and the owner (OS version, addresses, names, certificate, mail relay, gateway registration, backup share, how files are brought in).",
    "Pilot VM created: 16 vCPU, 64 GB RAM, 1 TB fast SSD as OS disk, disk A and disk B; GPU if available.",
    "Chapter 4 done: Rocky Linux 9 updated, accounts and SSH keys, chrony, disks (XFS ftype=1), Docker, SELinux enforcing, firewalld zones, performance settings; snapshot taken.",
    "DNS: the portal host name; internal names `ai.aslms.internal`, `db.aslms.internal`, `redis.aslms.internal` (section 2.5).",
    "Network firewall: 443/80 from the users' network only; SSH from the admin network; outbound to the gateway, the mail relay, the ClamAV source (or mirror / offline), NTP, DNS, the backup share.",
    "Backup share mounted as `BACKUP_DIR`, writable by uid 10001; off-site copy and snapshot schedule agreed.",
    "Court-data credentials and the Super Administrator's e-mail received securely; release code and images on the VM, checksums verified.",
  ]));
  add(H2("10.2 Go-live (from the runbook's pilot go-live checklist)"));
  add(box([
    "`aslms ops preflight` passes with `APP_ENV=prod`.",
    "Only 443 and 80 reachable from another machine (5433, 6379, 8000, 3000, 3310 and 11434 closed).",
    "TLS from a user PC: certificate trusted, `http://` redirects, another host name refused.",
    "Throttling checked (30 quick sign-ins give 429 `throttled`). EICAR refused through the proxy.",
    "First backup on the share outside the VM and restore check passed; restore drill time recorded.",
    "PgBouncer in the path (`SHOW POOLS` lists `aslms_app` traffic; sessions in `pg_stat_activity` come from `pgbouncer`).",
    "Monitoring: Prometheus targets up, Grafana overview live, a ClamAVDown test alert reached `OPS_ALERT_EMAIL`.",
    "No SELinux denials after a full day.",
    "Load counts and the sample check recorded (`aslms ops load-report --format md`, `aslms ops sample-cnrs --seed <n> --format md`).",
    "The government mail relay checked with a real sign-in. Super Administrator signed in; `ASLMS_SUPERADMIN_PASSWORD` cleared; `ca.key` off the VM.",
    "Court data on with the owner's authority; the backdated collection started if wanted.",
    "Case Assistant: the Case Assistant Model card green, or the Assistant off.",
    "The mapping data for the pilot department entered (owner).",
  ]));
  add(H2("10.3 After every update"));
  add(box([
    "Release notes read; users notified; snapshot and manual backup taken; previous release at hand.",
    "Code and images from the same release (checksums or signature verified; `migrate` did not exit 5); a `pre-migrate` backup exists.",
    "Started with the switch as before; `docker compose ps` all healthy; `init` exited 0.",
    "A test sign-in; the portal page, System Health and the data-health screen load; `aslms data-load status` shows the queue moving.",
    "New settings and one-off steps from the release notes done (for example everyone signing in again).",
    "No new SELinux denials; alert silences removed; users told the window is over.",
    "Previous release kept until the new one has run cleanly for a few days.",
  ]));
}

// ===================================================================== PART 2
function part2() {
  partPage("Part 2. Full hosting for about 1,000 users", "For after senior management approves the pilot. Prepare VMs when asked; deploy when backlog rows 192 and 194 are built.", [
    "Chapter 11 gives the multi-VM layout, roles and sizes; chapter 12 the network; chapter 13 the preparation of each VM and the AI server.",
    "Chapter 14 covers the staging VM, releases and patch updates for the full layout; chapter 15 the multi-VM installer (row 194).",
    "Chapter 16 is the move from the one-VM pilot to the full layout, with no data lost.",
    "Chapters 4 (Rocky Linux 9 preparation), 8 (updates) and 9 (operating) of Part 1 apply to each VM unless stated otherwise.",
  ]);
  add(LATER("Planned: backlog row 192 `scale-out-load-test` and row 194 (installer round 2)", [
    "Row 192 will deliver the multi-server Compose files; the code changes that let the API run in several processes on several servers (shared limits, multi-process metrics, a shared document store checked for safe writes); a PostgreSQL standby; numbered releases and signed update files; the move procedure; and a 1,000-user load test. None of this exists yet. Do not split the current `compose.yml` across servers: the `scheduler` and `worker` must run exactly once, and the per-process limits are not yet shared.",
  ]));
}

// ===== 11 =====
function s11() {
  add(H1("11. Layout, roles and sizes"));
  add(P("Indicative roles and sizes from the owner's infrastructure suggestion of 27 October 2026, to be confirmed by the row 192 design:"));
  add(table(["Role", "Count", "Size (each)", "What will run there"], [
    ["Load balancer / proxy", "2 (or the data centre's own)", "Data centre's choice", "TLS and distribution to the app servers"],
    ["App server", "2", "8 vCPU, 16 GB RAM, 100 GB + 30 GB for releases", "`web` and `api` (4–6 API processes each)"],
    ["Worker server", "1", "4 vCPU, 16 GB RAM, 100 GB + 30 GB for releases", "`scheduler`, `worker`, Redis, ClamAV (exactly one scheduler and one worker)"],
    ["PostgreSQL", "2 (main + standby)", "8 vCPU, 32 GB RAM, 500 GB SSD", "PostgreSQL with PgBouncer and a streaming standby"],
    ["Shared storage (NAS)", "1", "1 TB", "The document store, shared by the servers"],
    ["AI-model server", "1", "8–16 vCPU, 64 GB RAM, NVIDIA L4 24 GB", "Ollama (or later SourceTrace), private address only"],
    ["Monitoring", "1", "4 vCPU, 8 GB RAM, 200 GB", "Prometheus, Alertmanager, Grafana watching every host"],
    ["Staging", "1", "8 vCPU, 32 GB RAM, 300 GB SSD, no GPU", "Each update first, on a restored production backup"],
    ["Backup storage", "1", "2 TB", "Dumps and the store mirror, separate from all servers; staging restores from it"],
    ["Private image registry (optional)", "0–1", "2 vCPU, 4 GB RAM, 200 GB", "Only if the data centre allows it; not needed for file-based updates"],
  ], [2000, 1700, 2500, CW - 6200]));
  add(P("**Total:** about 9 VMs plus the GPU server and 1 TB of shared storage. Links between hosts are to be encrypted (row 192)."));
}

// ===== 12 =====
function s12() {
  add(H1("12. Network for the multi-VM layout"));
  add(table(["From → To", "Purpose", "Rule"], [
    ["Users → load balancer", "The portal over HTTPS", "443 (80 redirect) from the users' network"],
    ["Load balancer → app servers", "The proxy / portal", "Set `PROXY_TRUSTED_UPSTREAM` to the load balancer's range"],
    ["App and worker servers → PostgreSQL (PgBouncer)", "The database", "PgBouncer's port, from the app and worker servers only (encrypted, row 192)"],
    ["App servers → worker server", "Redis, ClamAV", "Their ports from the app servers only (encrypted, row 192)"],
    ["App servers → AI server", "Ollama (or SourceTrace)", "11434 from the app servers only"],
    ["App and worker servers → NAS", "The document store", "As the data centre specifies"],
    ["PostgreSQL main → standby", "Streaming replication", "Between the two database VMs only"],
    ["Monitoring → every VM", "Metrics", "Exporter ports from the monitoring VM only"],
    ["Worker (and app) servers → court-data gateway", "NAPIX", "443 outbound; **never from staging**"],
    ["Servers → mail relay", "Sign-in codes, alerts", "`SMTP_PORT`; staging only to the test-inbox relay"],
    ["Every VM → NTP, DNS, repositories; admins → every VM", "Time, names, updates; SSH", "As in Part 1"],
  ], [3300, 2600, CW - 5900]));
  add(P("The exact ports and the per-role Compose files come with row 192. Annexure A lists the Part 1 matrix and the Part 2 additions."));
}

// ===== 13 =====
function s13() {
  add(H1("13. Preparing the VMs and the AI server"));
  add(P("For every VM, carry out chapter 4 (Rocky Linux 9, updates, accounts, chrony, disks, Docker, SELinux, firewalld zones for its role, performance settings, hardening). Role notes:"));
  add(table(["Role", "Notes"], [
    ["PostgreSQL main and standby", "The fastest SSD; the `aslms-db` tuned profile (section 4.10); Docker's data on the database disk."],
    ["App and worker servers", "About 30 GB extra for the previous release's images and update files; the NAS mounted for the document store (with the SELinux context option of section 4.8)."],
    ["Staging", "As an app VM sized for the whole stack; no route to the court-data gateway; mail only to a test inbox (chapter 14)."],
    ["Monitoring", "Disk for 30 days of metrics from every host."],
    ["AI server", "No ASLMS stack; the NVIDIA driver and Ollama (below)."],
  ], [2600, CW - 2600]));
  add(H2("13.1 The AI server"));
  add(P("The steps are those of chapter 6 (sections 6.2, 6.3 and 6.5), with two differences: Ollama listens on the AI server's private address, and the firewall opens 11434 to the app servers only."));
  add(code([
    "sudo systemctl edit ollama",
    "[Service]",
    "Environment=\"OLLAMA_HOST=<AI server private address>:11434\"",
    "Environment=\"OLLAMA_KEEP_ALIVE=-1\"",
    "Environment=\"OLLAMA_NUM_PARALLEL=<equal to ASSISTANT_OLLAMA_SLOTS>\"",
    "",
    "sudo firewall-cmd --permanent --new-zone=aslms-app",
    "sudo firewall-cmd --permanent --zone=aslms-app --add-source=<app server address>/32     # repeat for each app server",
    "sudo firewall-cmd --permanent --zone=aslms-app --add-port=11434/tcp",
    "sudo firewall-cmd --reload",
  ]));
  add(P("Ollama has no authentication or TLS of its own: keep it on a private segment reachable only by the app servers (Annexure D: whether this link must be encrypted). The `ai.aslms.internal` record then points to this server. The 24 GB L4 also allows a larger model than `qwen3.5:4b` (the owner's choice, `ASSISTANT_OLLAMA_MODEL`)."));
}

// ===== 14 =====
function s14() {
  add(H1("14. Staging, releases and patch updates"));
  add(H2("14.1 The staging VM"));
  add(P("Each update is proved on staging, on production-sized data inside the data centre, before production. Staging is set up like production and restored from the latest production backup before each update (the disaster-restore steps of section 9.3); the data never leaves the data centre."));
  add(RULE("Staging safety rules", [
    "**The court-data switch stays OFF on staging.** It uses the same credentials and would consume production's hourly allowance. Block the gateway from staging at the network as well.",
    "**E-mail goes only to a test inbox.** The restored copy holds real officers' addresses: no alert, digest or sign-in code may reach them. Point the `SMTP_*` settings at a relay or mailbox that delivers only to a test inbox.",
    "**AI:** the production AI server only out of hours, or none. (Preview mode is refused by the preflight when `APP_ENV=prod`; Annexure D.)",
  ]));
  add(H2("14.2 Releases and the two-step update"));
  add(P("Releases, release notes, build-once delivery, the `migrate` guard and the update kinds are as in sections 8.2 and 8.3. In the full layout the data centre's two steps are:"));
  add(LATER("Planned: rows 192 and 194", [
    "**Step 1.** Receive one signed update file, for example `aslms-1.4.1.update`.",
    "**Step 2.** Run `sudo aslms-setup upgrade <file>` on **staging**; when staging passes, run the same command for **production** in the window. The command updates each role in the right order, with the database step once.",
  ]));
  add(steps([
    "Refresh staging from last night's production backup; start it with court data off and e-mail to the test inbox.",
    "Apply the update on staging; run the checks (section 10.3); time the migration.",
    "Only when staging passes, apply it to production in the window (section 8.4).",
    "Rollback as in section 8.6: the `pre-migrate` backup and the previous images.",
  ]));
}

// ===== 15 =====
function s15() {
  add(H1("15. The multi-VM installer"));
  add(LATER("Planned: backlog row 194, installer round 2 (built with row 192 after the pilot is approved)", ["This chapter describes the plan; it will be updated when the installer is built."]));
  add(H2("15.1 Roles on new VMs"));
  add(P("On each new VM, `sudo ./aslms-setup` with its role. Each role does chapter 4 for its VM and installs only its part of ASLMS:"));
  add(table(["Role", "Installs"], [
    ["`database`", "PostgreSQL and PgBouncer (main, or standby with replication)"],
    ["`app`", "`web` and `api`, behind the load balancer"],
    ["`worker`", "`scheduler`, `worker`, Redis, ClamAV (exactly one)"],
    ["`ai`", "NVIDIA driver, Ollama on the private address, the model (chapter 13.1)"],
    ["`staging`", "The whole stack with the staging rules: court data off, e-mail to a test inbox, AI preview or none (section 14.1)"],
  ], [2000, CW - 2000]));
  add(H2("15.2 Guided moves"));
  add(code([
    "sudo aslms-setup move ai --to <gpu-vm>",
    "sudo aslms-setup move documents --to <nas>",
    "sudo aslms-setup move database --to <db-vm>",
    "sudo aslms-setup check",
  ]));
  add(P("Each move runs a check and a backup first and stays undoable until confirmed. The database switch happens only on an administrator's yes in the maintenance window. `aslms-setup check` confirms the result. Chapter 16 describes the order."));
}

// ===== 16 =====
function s16() {
  add(H1("16. Moving from one VM to many"));
  add(LATER("Planned: backlog row 192 (procedure) and row 194 (guided moves); after the pilot is approved", ["The move is to be designed, tested and rehearsed on staging before it is used. This chapter describes the planned order."]));
  add(P("The move loses no data. Each step changes one part, can be checked, and is rehearsed on the staging VM first. Thanks to the set-up of section 2.5, most steps only change what an internal name points to."));
  add(table(["#", "What moves", "How", "Downtime"], [
    ["1", "AI to the GPU server", "Install the AI server (chapter 13.1), pull the model, point `ai.aslms.internal` (or `ASSISTANT_OLLAMA_URL`) at it, `aslms assistant warm`", "None"],
    ["2", "Staging VM", "Build staging from a backup (chapter 14); rehearse each next step there", "None"],
    ["3", "Documents to the NAS", "Background copy of `data/store` to the NAS, then a short final sync and remount; skip if already on the NAS", "Minutes"],
    ["4", "Database to its own VM", "A live replica kept in sync on the database VM, switched over in a short window by pointing `db.aslms.internal` at it (alternatively backup and restore: 1–2 hours)", "About 5–15 minutes"],
    ["5", "A standby database", "A second replica on the standby VM", "None"],
    ["6", "App servers and the load balancer", "App servers added behind the load balancer; the original VM becomes an app or worker server; exactly one scheduler and one worker", "A short switch of the portal's address"],
  ], [600, 2200, 5000, CW - 7800]));
  add(P("**Total downtime:** about one short evening window (step 4, plus the portal switch of step 6 if done the same evening). Each step with downtime follows the maintenance-window rules of section 8.4: snapshot and backup first, users notified, court-data switch carried on every start."));
}

// ===================================================================== Annexures
function annexA() {
  add(H1("Annexure A. Port and firewall matrix"));
  add(H3("Part 1: the pilot VM"));
  add(table(["Port", "Service", "Bound to / reachable from", "Firewall"], [
    ["443/tcp", "`proxy` (HTTPS portal)", "`PROXY_BIND`; users' network", "Allow from users' network (zone `aslms-users`)"],
    ["80/tcp", "`proxy` (redirect only)", "`PROXY_BIND`; users' network", "Allow from users' network"],
    ["22/tcp", "SSH", "Administrators' network", "Zone `aslms-admin` (recommendation)"],
    ["3001, 9090, 9093, 5555/tcp", "Grafana, Prometheus, Alertmanager, Flower", "127.0.0.1 only", "Never open; SSH tunnel"],
    ["5432, 6432, 6379, 3310/tcp", "`postgres`, `pgbouncer`, `redis`, `clamav`", "Docker network only", "Never published"],
    ["8000, 9100, 3000, 9108/tcp", "`api`, its metrics, `web`, `ops-exporter`", "Docker network only", "Never published"],
    ["11434/tcp", "Ollama on the VM (row 188)", "VM private address, used by its own containers", "Never opened"],
    ["443/tcp outbound", "Court-data gateway (`NAPIX_BASE_URL`)", "From the VM", "Allow (outbound address registration: to be confirmed)"],
    ["`SMTP_PORT` outbound (587)", "Mail relay", "From the VM", "Allow"],
    ["443/tcp outbound", "ClamAV signatures; Rocky, Docker, NVIDIA repositories; Ollama library", "From the VM", "Allow, or mirrors / offline mode / files copied in"],
    ["NFS (as specified)", "Backup share", "From the VM", "Allow to the backup storage only"],
    ["123/udp, 53", "NTP, DNS", "From the VM", "Allow to the data centre's servers"],
  ], [1900, 2700, 2700, CW - 7300]));
  add(H3("Part 2 additions"));
  add(table(["Port", "Service", "From", "Firewall"], [
    ["443/tcp", "App servers' proxy", "Load balancer", "Allow from the load balancer only"],
    ["PgBouncer port", "Database VM", "App and worker servers", "Allow from them only; encrypted (row 192)"],
    ["Replication", "PostgreSQL main → standby", "Database VMs", "Between them only"],
    ["Redis, ClamAV ports", "Worker server", "App servers", "Allow from them only; encrypted (row 192)"],
    ["11434/tcp", "AI server", "App servers", "Zone `aslms-app`"],
    ["Exporter ports", "Every VM", "Monitoring VM", "Allow from it only"],
    ["443/tcp", "Staging portal", "Admins and testers", "Allow from them only; **no outbound to the gateway**"],
    ["Registry port (if used)", "Private image registry", "ASLMS VMs", "To be confirmed"],
  ], [1900, 2700, 2700, CW - 7300]));
}

function annexB() {
  add(H1("Annexure B. Environment variables"));
  add(P("Names and purpose only; values are never written here. **Secret** marks a value to generate or receive securely. `.env.example` documents each with its default and range."));
  add(table(["Group", "Variables", "Purpose"], [
    ["Environment", "`APP_ENV`, `LOG_LEVEL`, `TIMEZONE`", "`prod` in the data centre; IST"],
    ["Compose", "`COMPOSE_FILE`, `COMPOSE_PATH_SEPARATOR`, `COMPOSE_PROFILES`", "Files and profiles"],
    ["PostgreSQL", "`POSTGRES_USER`, `POSTGRES_PASSWORD` (secret), `POSTGRES_DB`, `ASLMS_APP_PASSWORD` (secret), `ASLMS_READONLY_PASSWORD` (secret), `PG_SHARED_BUFFERS`, `PG_EFFECTIVE_CACHE_SIZE`, `PG_WORK_MEM`, `PG_MAINTENANCE_WORK_MEM`, `PG_MAX_CONNECTIONS`", "Database roles and memory"],
    ["Host-run only", "`DATABASE_URL_SYNC`, `ASLMS_MIGRATE_URL`, `REDIS_URL`, `POSTGRES_HOST_PORT`, `API_HOST_PORT`, `WEB_HOST_PORT`", "Development; not used by the production stack"],
    ["PgBouncer and budget", "`PGBOUNCER_MAX_CLIENT_CONN`, `PGBOUNCER_DEFAULT_POOL_SIZE`, `PGBOUNCER_MAX_PREPARED_STATEMENTS`, `DB_APART_POOL_SIZE`, `DB_APART_POOL_TIMEOUT_SECONDS`, `NAPIX_REQUEST_SLOTS`, `NAPIX_REQUEST_WAIT_SECONDS`", "Pooling and the connection budget"],
    ["Redis", "`REDIS_PASSWORD` (secret)", "Redis password"],
    ["Backups", "`BACKUP_DIR`, `BACKUP_INTERVAL_HOURS`, `BACKUP_KEEP_RECENT_HOURS`, `BACKUP_KEEP_DAILY`, `BACKUP_KEEP_WEEKLY`, `BACKUP_KEEP_MONTHLY`, `BACKUP_KEEP_PREMIGRATE`", "Where, how often, retention"],
    ["Monitoring", "`GRAFANA_ADMIN_PASSWORD` (secret), `FLOWER_BASIC_AUTH` (secret, `user:password`), `OPS_ALERT_EMAIL`, `PROMETHEUS_RETENTION`", "Logins and alert recipient"],
    ["Proxy", "`PROXY_BIND`, `PROXY_HTTPS_PORT`, `PROXY_HTTP_PORT`, `PROXY_SESSION_RATE`, `PROXY_SESSION_BURST`, `PROXY_API_RATE`, `PROXY_API_BURST`, `PROXY_CONN_PER_IP`, `PROXY_TRUSTED_UPSTREAM`", "Ports and throttling"],
    ["Sign-in", "`ASLMS_JWT_SECRET` (secret), `ASLMS_ACCESS_TOKEN_MINUTES`, `ASLMS_SUPERADMIN_EMAIL`, `ASLMS_SUPERADMIN_PASSWORD` (secret, temporary), `OTP_TTL_MINUTES`, `OTP_MAX_ATTEMPTS`, `OTP_RESEND_SECONDS`, `OTP_MAX_PER_HOUR`, `LOGIN_MAX_FAILURES`, `LOGIN_LOCK_MINUTES`", "Tokens, first Super Administrator, codes, lock-out"],
    ["Sessions", "`SESSION_IDLE_MINUTES` (30), `SESSION_WARNING_SECONDS` (120), `SESSION_MAX_HOURS` (12)", "Idle sign-out, warning, hard limit"],
    ["Court data (NAPIX)", "`NAPIX_ENABLED` (command line only), `NAPIX_CLIENT_ID`, `NAPIX_CLIENT_SECRET`, `NAPIX_DEPT_ID`, `NAPIX_AUTH_KEY` (all secret), `NAPIX_HASH_KEY`, `NAPIX_BASE_URL`, `NAPIX_EST_CODE`, `NAPIX_STATE_CODE`, `NAPIX_VERSION`, and the `NAPIX_*` rate, window, reserve, search, fault and advocate-search tunables", "Gateway, credentials, quota"],
    ["System health", "`NAPIX_HEALTH_CHECK_MIN_SECONDS`, `HEALTH_TEST_*`, `HEALTH_POOL_ADDRESS`, `HEALTH_POSTGRES_DIRECT_*`, `NAPIX_DOCS_DIR`, `HEALTH_TOKEN_CHECK_MIN_SECONDS`, `HEALTH_RAW_MAX_BYTES`", "Live-test limits"],
    ["Documents", "`STORAGE_DIR`, `CAUSELIST_DIR`, `UPLOAD_MAX_BYTES`, `CLAMAV_HOST`, `CLAMAV_PORT`, `CLAMAV_TIMEOUT_SECONDS`, `TEXT_EXTRACT_BATCH`, `ATTACHMENTS_MAX_FILES`, `NOTE_MAX_CHARS`, `NOTE_DRAFTS_MAX`", "Store, uploads, scanning"],
    ["SourceTrace", "`SOURCETRACE_ENABLED`, `SOURCETRACE_BASE_URL`, `SOURCETRACE_API_KEY` (secret), `SOURCETRACE_BATCH`, `SOURCETRACE_RUN_SECONDS`, `SOURCETRACE_TIMEOUT_SECONDS`, `SOURCETRACE_MAX_ATTEMPTS`", "Off until the connector exists"],
    ["Case Assistant", "`ASSISTANT_MODE`, `ASSISTANT_TIMEOUT_SECONDS`, `ASSISTANT_*` limits; `ASSISTANT_OLLAMA_URL`, `ASSISTANT_OLLAMA_MODEL`, `ASSISTANT_OLLAMA_NUM_CTX`, `ASSISTANT_OLLAMA_NUM_PREDICT`, `ASSISTANT_OLLAMA_KEEP_ALIVE`, `ASSISTANT_OLLAMA_TIMEOUT_SECONDS`, `ASSISTANT_OLLAMA_SLOTS`, `ASSISTANT_OLLAMA_SLOT_WAIT_SECONDS`, `ASSISTANT_OLLAMA_SOURCES`, `ASSISTANT_OLLAMA_SOURCE_CHARS`, `ASSISTANT_OLLAMA_HISTORY_TURNS`, `ASSISTANT_OLLAMA_INTERNAL_CHARS`, `ASSISTANT_OLLAMA_HEARINGS`", "Engine and limits; no API key for the local model"],
    ["Mail", "`MAIL_BACKEND`, `MAILTRAP_API_TOKEN` (secret), `MAILTRAP_API_URL`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD` (secret), `SMTP_STARTTLS`, `SMTP_FROM`, `SMTP_FROM_NAME`, `MAIL_TIMEOUT_SECONDS`", "The mail relay (mandatory)"],
    ["Portal", "`PORTAL_BASE_URL`, `COOKIE_SECURE`, `RELAY_TIMEOUT_SECONDS`, `ASLMS_SUBNET`, `WEB_IP`", "Address and private network"],
    ["Alerts, reports, data collection", "`ALERT_*`, `COURT_SITTING_TIME`, `REQUEST_DUE_SOON_DAYS`, `NOTIFY_*`, `REPORT_*`, `DASHBOARD_LIST_SIZE`, `DATA_LOAD_ESTIMATE_WINDOW_DAYS`, `NAPIX_DISCOVERY_SHARE`, `DISCOVERY_FROM_YEAR`, `NEXT_DATE_*`, `DISPOSED_REFRESH_*`, `CAUSELIST_RECHECK_*`, `NAPIX_CALL_LOG_*`", "Behaviour limits; defaults normally kept"],
  ], [2200, 4700, CW - 6900]));
}

function annexC() {
  add(H1("Annexure C. Command reference"));
  add(P("Run in `/srv/aslms`. `<switch>` means `{ON}` or `NAPIX_ENABLED=false` as authorised; it is required on every `up`."));
  add(table(["Command", "What it does"], [
    ["`<switch> docker compose up -d --wait`", "Start or apply `.env` changes (`init`: preflight, migration guard, role passwords, seed)"],
    ["`docker compose ps` / `docker compose logs <service>`", "State and logs"],
    ["`docker compose stop api worker scheduler web pgbouncer`", "Stop before `migrate` or a restore"],
    ["`sha256sum -c <file>.sha256` / `docker load -i <images file>`", "Verify and load a release's images"],
    ["`docker compose build` and `docker compose --profile ops build migrate`", "Build on the VM (runbook alternative)"],
    ["`docker compose --profile ops run --rm migrate`", "The explicit upgrade: backup, migrate, seed, audit row"],
    ["`docker compose run --rm --no-deps init aslms ops preflight`", "Check the settings"],
    ["`docker compose run --rm --no-deps -v ./infra/proxy/certs:/certs init aslms ops make-cert --host <name> --ip <address> --out /certs`", "Internal CA and certificate"],
    ["`docker compose exec api aslms users create-super-admin --email <address>`", "First Super Administrator"],
    ["`docker compose exec api aslms alerts test-mail --to <address>`", "Test the mail relay"],
    ["`docker compose exec api aslms documents scan-check`", "ClamAV EICAR test"],
    ["`docker compose exec api aslms system-health` / `aslms data-health`", "Service checks / queue, jobs, mail, court data"],
    ["`docker compose exec api aslms data-load status | start --from --to | pause --reason | resume`", "The backdated collection"],
    ["`docker compose exec backup aslms ops backup [--tag <tag>]` / `backup-status` / `restore-check`", "Backups"],
    ["`docker compose --profile ops run --rm migrate aslms ops restore --dump … --roles … --confirm-overwrite aslms --store-from /backups/store`", "Disaster restore, rollback, staging refresh"],
    ["`docker compose exec api aslms ops load-report` / `sample-cnrs --seed <n>`", "Load counts, sample check"],
    ["`docker compose exec api aslms ops repair-jobs --older-than 6h [--dry-run]`", "Repair jobs left `running`"],
    ["`docker compose exec api aslms ops pool-check …`", "Connection-pool check (read-only)"],
    ["`docker compose exec ops-exporter aslms ops metrics --once`", "One reading of the operations exporter"],
    ["`docker compose exec api aslms users sign-out --email <address>`", "Sign a login out everywhere"],
    ["`docker compose exec api aslms assistant warm | status | check`", "Load the local model; show the engine; the Case Assistant's consistency counts (each 0)"],
    ["`sudo aslms-setup [check | upgrade <file> | rollback]` (row 193)", "The one-VM installer (planned)"],
    ["`sudo aslms-setup move ai|documents|database --to <target>` (row 194)", "Guided moves (planned)"],
    ["`getenforce`, `ausearch -m avc -ts recent`, `restorecon -R`; `firewall-cmd --get-active-zones`; `tuned-adm active`; `chronyc tracking`; `xfs_info`", "Host checks"],
  ], [5600, CW - 5600]));
}

function annexD() {
  add(H1("Annexure D. Information to be confirmed"));
  add(P("The repository does not settle these points; each is confirmed with the data centre or the owner. Where the guide gives a recommendation, it is noted."));
  add(table(["#", "Point", "With", "Guide's recommendation"], [
    ["1", "The operating system's major version: Rocky Linux 9 is the owner's choice (RHEL 9 or AlmaLinux 9 also fit); Rocky Linux 10 if the data centre is on RHEL 10, with the vendor commands rechecked", "Data centre / owner", "Rocky Linux 9 (section 4.1)"],
    ["2", "The pilot VM's size, GPU availability, disks and IP addresses", "Data centre", "Sections 2.2 and 2.5"],
    ["3", "Fast SSD class and IOPS for the database disk", "Data centre", "Section 4.10"],
    ["4", "Portal host name; internal names `ai.`, `db.`, `redis.aslms.internal` in the data centre's DNS", "Data centre / owner", "Section 2.5"],
    ["5", "Certificate source and how `ca.crt` reaches user PCs", "Data centre / owner", "NIC or data-centre certificate"],
    ["6", "Mail relay, sender domain and credentials; for staging (Part 2) a relay delivering only to a test inbox", "Data centre / NIC / owner", "The State's government relay"],
    ["7", "Whether the court-data gateway requires the outbound (NAT) address to be registered", "Owner / e-Committee", "—"],
    ["8", "How release and update files are brought in (secure transfer through a jump host, or approved media); whether a private registry is allowed", "Data centre", "File-based delivery (section 8.2)"],
    ["9", "Access to package repositories (Rocky, Docker, NVIDIA), ClamAV signatures and Ollama's library, or mirrors and offline mode", "Data centre", "The data centre's mirrors"],
    ["10", "Backup share type and size, uid 10001 write access (NFS root squashing), SELinux context option, off-site copy, snapshot schedule", "Data centre", "2 TB off the VM; snapshots before updates"],
    ["11", "Whether Docker's container SELinux labels (`selinux-enabled`) are required by policy", "Data centre", "After a clean trial (section 4.8)"],
    ["12", "Acceptable data-loss window (about 6 hours now)", "Owner", "—"],
    ["13", "Who receives monitoring alerts", "Owner", "The Super Administrator's mailbox"],
    ["14", "Whether the privileged `cadvisor` (`monitoring-host`) is allowed", "Data centre", "—"],
    ["15", "A load balancer in front of the proxy (`PROXY_TRUSTED_UPSTREAM`)", "Data centre", "—"],
    ["16", "The AI model and timeouts without a GPU; Secure Boot policy for the NVIDIA module; the exact Ollama version (live check, row 195)", "Owner / data centre", "Section 6.7"],
    ["17", "Whether the link to a separate AI server (Part 2) must be encrypted", "Data centre", "Private segment"],
    ["18", "AI on staging: preview mode is refused with `APP_ENV=prod`; the production AI server out of hours, or none", "Owner / row 194 design", "None, or out of hours"],
    ["19", "SSH policy, jump host, hardening baseline", "Data centre", "Sections 3.6 and 4.11"],
    ["20", "Start date of the backdated collection; the maintenance window", "Owner / data centre", "Weekday 21:00–23:00 or Sunday after 09:00"],
    ["21", "Where the installer keeps its log; its offline bundle; release numbering and the signing of update files", "Rows 192 / 193 design", "—"],
    ["22", "The multi-VM layout, its ports, Compose files and the move procedure; NFS safe writes for the document store", "Rows 192 / 194 design", "Part 2 is indicative"],
  ], [500, 4300, 1700, CW - 6500]));
}

documentControl(); s1(); part1(); s2(); s3(); s4(); s5(); s6(); s7(); s8(); s9(); s10(); part2(); s11(); s12(); s13(); s14(); s15(); s16(); annexA(); annexB(); annexC(); annexD();



const footer = new Footer({ children: [new Paragraph({
  border: { top: { style: BorderStyle.SINGLE, size: 4, color: LINE, space: 6 } },
  children: [
    new TextRun({ text: "ASLMS Hosting Guide · Government of Assam · For official use", size: 16, color: MUTED, font: FONT }),
    new TextRun({ text: "\tPage ", size: 16, color: MUTED, font: FONT }),
    new TextRun({ children: [PageNumber.CURRENT], size: 16, color: MUTED, font: FONT }),
  ],
  tabStops: [{ type: "right", position: CW }],
})] });

const pageProps = { page: { size: { width: PAGE_W, height: PAGE_H, orientation: PageOrientation.PORTRAIT }, margin: { top: MARGIN, bottom: MARGIN, left: MARGIN, right: MARGIN } } };

const doc = new Document({
  creator: "Government of Assam",
  lastModifiedBy: "Government of Assam",
  title: "ASLMS Hosting Guide",
  subject: "Assam State Litigation Management System",
  description: "Step-by-step hosting guide for data-centre system administrators: VM preparation, deployment, updates and operation of ASLMS",
  styles: {
    default: { document: { run: { font: FONT, size: 21, color: INK } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true, run: { size: 34, bold: true, color: NAVY, font: FONT }, paragraph: { spacing: { before: 0, after: 240 }, outlineLevel: 0, border: { bottom: { style: BorderStyle.SINGLE, size: 12, color: GOLD, space: 6 } } } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true, run: { size: 26, bold: true, color: TEAL, font: FONT }, paragraph: { spacing: { before: 280, after: 120 }, outlineLevel: 1, keepNext: true } },
      { id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true, run: { size: 22, bold: true, color: NAVY, font: FONT }, paragraph: { spacing: { before: 200, after: 80 }, outlineLevel: 2, keepNext: true } },
    ],
  },
  numbering: { config: NUMBERING },
  sections: [
    { properties: pageProps, children: cover() },
    { properties: pageProps, footers: { default: footer }, children: C },
  ],
});

Packer.toBuffer(doc).then((buf) => { fs.writeFileSync(process.argv[2] || path.join(__dirname, "ASLMS_Hosting_Guide.docx"), buf); console.log("written"); });
