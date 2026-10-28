// ASLMS software documentation (Government submission). Run: node build.js <out.docx>
const fs = require("fs");
const path = require("path");
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell, WidthType, ShadingType,
  AlignmentType, HeadingLevel, BorderStyle, PageBreak, Footer, Header, PageNumber, LevelFormat,
  VerticalAlign, TableLayoutType, PageOrientation,
} = require("docx");

const ref = JSON.parse(fs.readFileSync(path.join(__dirname, "ref.json"), "utf8"));

// ---------- palette and page ----------
const NAVY = "15335A", TEAL = "0E7C7B", GOLD = "B8862B", INK = "1F2933", MUTED = "5B6770";
const PALE = "EEF3F8", PALE_TEAL = "E6F4F3", PALE_GOLD = "FBF4E6", LINE = "C9D3DD", WHITE = "FFFFFF";
const FONT = "Calibri";
const PAGE_W = 11906, PAGE_H = 16838, MARGIN = 1134;
const CW = PAGE_W - 2 * MARGIN; // 9638

// ---------- inline markup: **bold** ----------
function runs(text, opts = {}) {
  const out = [];
  String(text).split(/(\*\*[^*]+\*\*)/).forEach((part) => {
    if (!part) return;
    const bold = part.startsWith("**") && part.endsWith("**");
    out.push(new TextRun({ text: bold ? part.slice(2, -2) : part, bold: bold || opts.bold, color: opts.color, size: opts.size, italics: opts.italics, font: FONT }));
  });
  return out;
}

const P = (text, o = {}) => new Paragraph({ children: runs(text, o), spacing: { after: o.after ?? 120, before: o.before ?? 0, line: o.line ?? 276 }, alignment: o.align });
const H1 = (text) => new Paragraph({ heading: HeadingLevel.HEADING_1, pageBreakBefore: true, children: [new TextRun({ text, font: FONT })] });
const H2 = (text) => new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun({ text, font: FONT })] });
const H3 = (text) => new Paragraph({ heading: HeadingLevel.HEADING_3, children: [new TextRun({ text, font: FONT })] });
const B = (text, level = 0) => new Paragraph({ numbering: { reference: "bullets", level }, children: runs(text), spacing: { after: 60, line: 276 } });
const N = (text, ref_ = "steps") => new Paragraph({ numbering: { reference: ref_, level: 0 }, children: runs(text), spacing: { after: 60, line: 276 } });
const pageBreak = () => new Paragraph({ children: [new PageBreak()] });
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
      String(c).split("\n").map((line) => new Paragraph({ children: runs(line, { size: 20, bold: o.boldFirst && i === 0 }), spacing: { after: 40 } })),
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
    rows: [new TableRow({ children: [cell(kids, CW, { fill, pad: 140, borders: { top: noBorder, bottom: noBorder, right: noBorder, left: { style: BorderStyle.SINGLE, size: 24, color: rule } } })] })],
  }), spacer(160)];
}

// ---------- brochure pieces ----------
function tile(title, body, fill, accent, width) {
  return cell([
    new Paragraph({ children: [new TextRun({ text: title, bold: true, color: accent, size: 24, font: FONT })], spacing: { after: 80 } }),
    new Paragraph({ children: runs(body, { size: 20, color: INK }), spacing: { after: 0, line: 264 } }),
  ], width, { fill, pad: 180, borders: { top: { style: BorderStyle.SINGLE, size: 18, color: accent }, bottom: noBorder, left: noBorder, right: noBorder } });
}
function gapCell(width) { return cell(new Paragraph({ children: [] }), width, { borders: { top: noBorder, bottom: noBorder, left: noBorder, right: noBorder } }); }

function tileGrid(items, cols, fills) {
  const gap = 200;
  const w = Math.floor((CW - gap * (cols - 1)) / cols);
  const widths = [];
  for (let i = 0; i < cols; i++) { widths.push(w); if (i < cols - 1) widths.push(gap); }
  const total = widths.reduce((a, b) => a + b, 0);
  const rows = [];
  for (let i = 0; i < items.length; i += cols) {
    const cells = [];
    for (let j = 0; j < cols; j++) {
      const it = items[i + j];
      const [fill, accent] = fills[(i + j) % fills.length];
      cells.push(it ? tile(it[0], it[1], fill, accent, w) : gapCell(w));
      if (j < cols - 1) cells.push(gapCell(gap));
    }
    rows.push(new TableRow({ cantSplit: true, children: cells }));
    if (i + cols < items.length) rows.push(new TableRow({ children: widths.map((ww) => cell(new Paragraph({ children: [], spacing: { after: 0 } }), ww, { borders: { top: noBorder, bottom: noBorder, left: noBorder, right: noBorder }, pad: 40 })) }));
  }
  return new Table({ width: { size: total, type: WidthType.DXA }, columnWidths: widths, rows, layout: TableLayoutType.FIXED, borders: noBorders });
}

function statStrip(stats) {
  const w = Math.floor(CW / stats.length);
  const widths = stats.map(() => w);
  return new Table({
    width: { size: w * stats.length, type: WidthType.DXA }, columnWidths: widths, layout: TableLayoutType.FIXED, borders: noBorders,
    rows: [new TableRow({ children: stats.map(([num, label], i) => cell([
      new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: num, bold: true, size: 40, color: i % 2 ? TEAL : NAVY, font: FONT })], spacing: { after: 20 } }),
      new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: label, size: 18, color: MUTED, font: FONT })], spacing: { after: 0 } }),
    ], w, { fill: PALE, pad: 160, borders: { top: noBorder, bottom: noBorder, left: i ? { style: BorderStyle.SINGLE, size: 6, color: WHITE } : noBorder, right: noBorder }, valign: VerticalAlign.CENTER })) })],
  });
}

function stepStrip(steps) {
  const arrowW = 360;
  const w = Math.floor((CW - arrowW * (steps.length - 1)) / steps.length);
  const widths = [];
  steps.forEach((_, i) => { widths.push(w); if (i < steps.length - 1) widths.push(arrowW); });
  const cells = [];
  steps.forEach(([n, title, body], i) => {
    cells.push(cell([
      new Paragraph({ children: [new TextRun({ text: n, bold: true, size: 36, color: GOLD, font: FONT })], spacing: { after: 40 } }),
      new Paragraph({ children: [new TextRun({ text: title, bold: true, size: 22, color: WHITE, font: FONT })], spacing: { after: 80 } }),
      new Paragraph({ children: runs(body, { size: 18, color: "DCE6F0" }), spacing: { after: 0, line: 252 } }),
    ], w, { fill: NAVY, pad: 180, borders: { top: noBorder, bottom: noBorder, left: noBorder, right: noBorder } }));
    if (i < steps.length - 1) cells.push(cell(new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: "▶", size: 28, color: GOLD, font: FONT })] }), arrowW, { valign: VerticalAlign.CENTER, borders: { top: noBorder, bottom: noBorder, left: noBorder, right: noBorder } }));
  });
  return new Table({ width: { size: widths.reduce((a, b) => a + b, 0), type: WidthType.DXA }, columnWidths: widths, layout: TableLayoutType.FIXED, borders: noBorders, rows: [new TableRow({ cantSplit: true, children: cells })] });
}

function band(text, sub) {
  return new Table({
    width: { size: CW, type: WidthType.DXA }, columnWidths: [CW], layout: TableLayoutType.FIXED, borders: noBorders,
    rows: [new TableRow({ children: [cell([
      new Paragraph({ children: [new TextRun({ text, bold: true, size: 34, color: NAVY, font: FONT })], spacing: { after: sub ? 40 : 0 } }),
      ...(sub ? [new Paragraph({ children: [new TextRun({ text: sub, size: 21, color: MUTED, font: FONT })], spacing: { after: 0 } })] : []),
    ], CW, { pad: 60, borders: { top: noBorder, left: noBorder, right: noBorder, bottom: { style: BorderStyle.SINGLE, size: 12, color: GOLD } } })] })],
  });
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
      tall("Every government case before the Gauhati High Court,", 28, "DCE6F0", { after: 40 }),
      tall("tracked in one place, from the court’s own data.", 28, "DCE6F0", { after: 1400 }),
      new Paragraph({ border: { top: { style: BorderStyle.SINGLE, size: 8, color: GOLD, space: 12 } }, children: [new TextRun({ text: "Software Documentation", size: 30, bold: true, color: WHITE, font: FONT })], spacing: { after: 60 } }),
      tall("Product overview · System requirements and design · Security · Operations", 21, "DCE6F0", { after: 0 }),
    ], CW, { fill: NAVY, pad: 600, borders: { top: noBorder, bottom: noBorder, left: noBorder, right: noBorder } })] })],
  });
  const meta = table(["Document", "Details"], [
    ["Title", "ASLMS Software Documentation"],
    ["Owner", "Government of Assam"],
    ["Version", "1.2"],
    ["Date", "28 October 2026"],
    ["Status", "Submitted for review"],
    ["Classification", "For official use"],
  ], [2600, CW - 2600], { boldFirst: true });
  return [block, spacer(400), ...meta];
}

// ---------- brochure ----------
function brochure() {
  const out = [];
  out.push(band("At a glance", "What ASLMS is and why it matters"));
  out.push(spacer(160));
  out.push(P("Government departments in Assam are party to tens of thousands of cases before the Gauhati High Court. Until now, finding a department’s cases, keeping track of hearing dates and knowing who holds a file has depended on manual effort spread across offices. **ASLMS brings it together**: it collects the court’s records through the official eCourts interface every day, recommends each case to the department it most likely belongs to, and gives the department everything it needs to act on time, with a permanent record of who did what.", { line: 300, after: 200 }));
  out.push(tileGrid([
    ["Official court data", "Cause lists, case records, orders and status come only from the official NAPIX interface of eCourts for the Gauhati High Court. No website scraping. Every answer is kept exactly as received."],
    ["Recommend, then claim", "The system scores every case for every department and recommends it. A case becomes a department’s only when a person in that department claims it. Nothing is assigned automatically."],
    ["Never miss a hearing", "Hearing reminders a week ahead and critical alerts within 48 hours, a personal calendar, a daily e-mail digest, and next dates read from new orders for confirmation."],
    ["Accountable file movement", "The case file moves from officer to officer with a remark, a pending action and a due date. Notes are permanent, and every significant action is written to the audit log."],
  ], 2, [[PALE, NAVY], [PALE_TEAL, TEAL], [PALE_TEAL, TEAL], [PALE, NAVY]]));
  out.push(spacer(280));
  out.push(statStrip([["17", "court APIs integrated"], ["10", "user types"], ["51", "grantable functions"], ["24", "case stages"], ["6 h", "backup interval"], ["0", "cloud AI services"]]));
  out.push(pageBreak());

  out.push(band("How it works", "From the court’s records to the officer who acts on them"));
  out.push(spacer(200));
  out.push(stepStrip([
    ["1", "Collect", "Every day the system fetches the cause lists, case records, status and orders from the court’s official interface."],
    ["2", "Recommend", "Each case is scored for every department from counsel codes, names, keywords, linked cases and watchlists."],
    ["3", "Claim and assign", "The department reviews its recommendations, claims its cases and assigns each to a unit and a dealing officer."],
    ["4", "Act and track", "Officers move the file, write notes, upload filings and receive alerts until the case is disposed."],
  ]));
  out.push(spacer(300));
  out.push(band("Who uses it"));
  out.push(spacer(120));
  out.push(...table(["User group", "What ASLMS gives them"], [
    ["Departments", "A case inbox with recommendations, claimed cases, transfers and the unclaimed pool; assignment to units and officers; department reports and hearing calendar."],
    ["Officers", "The cases with them, pending actions and due dates, the full case record with orders, notes and documents, and alerts by portal and e-mail."],
    ["Standing counsel", "The cases carrying their department’s counsel codes, and the notes and documents shared with counsel."],
    ["State oversight", "A read-only State-wide view: cases by department, hearings, unclaimed cases and overdue actions, with State reports."],
    ["Central operator", "Follow-up of unclaimed cases and data quality, court searches and suggestions to departments."],
    ["Auditors", "Read-only case records and the complete audit log with before-and-after values."],
    ["Super Administrator", "Offices, users and access, department mapping and scoring, data collection, system health and configuration."],
  ], [2400, CW - 2400], { boldFirst: true }));
  out.push(pageBreak());

  out.push(band("Features", "One portal for the whole life of a case"));
  out.push(spacer(160));
  out.push(tileGrid([
    ["Case inbox", "Recommended cases strongest first, with the reasons behind each score; claim, dismiss or suggest another department; department cases, transfers and the unclaimed pool."],
    ["Case page", "Summary, hearings, orders, documents, notes, timeline, parties, linked cases, custody and stage, all read from the ASLMS database."],
    ["Search", "Search ASLMS by CNR, case number, party or advocate, or the text of orders; search the High Court by CNR, case, filing number, party or advocate."],
    ["Hearings and alerts", "Bell and e-mail alerts, a personal calendar, department hearings and next dates read from orders for confirmation."],
    ["Cause list", "Any date and bench in court order, with each entry’s recommendation or owner, a Claim button and the original list."],
    ["Notes and documents", "Append-only notes with corrections linked to the original; uploads checked by content and scanned for viruses; visibility per item."],
    ["Case Assistant", "Questions answered from court records with every source cited. Prepared for the in-house SourceTrace service; until it is connected, answers may be written by a local model on Government servers, never a cloud service."],
    ["Dashboards and reports", "Personal, department and State dashboards; four reports with Excel and PDF export."],
    ["Administration", "Offices in the government hierarchy, users and memberships, user types and functions, department mapping and scoring."],
    ["Data collection", "Live overview with progress and finish estimates, collection on request, and automatic collection with load control."],
    ["System health", "The state of every court API and ASLMS service, with a limited, audited live test."],
    ["Audit log", "Every significant action, searchable by person, case, office and date, with before-and-after values."],
  ], 3, [[PALE, NAVY], [PALE_TEAL, TEAL], [PALE_GOLD, GOLD]]));
  out.push(spacer(240));
  out.push(...callout("Built for trust", [
    "**Own servers.** All data stays on government infrastructure. No public cloud service and no cloud AI.",
    "**Two-step sign-in.** Password plus a one-time code by e-mail at every sign-in; lock-out after repeated failures.",
    "**Visibility on the server.** What each person may see is decided by the server for every request, by office and role.",
    "**Nothing lost.** Legal records are never deleted; every court call is logged; backups every six hours with a weekly restore test.",
  ], PALE_GOLD, GOLD));
  return out;
}

// ---------- formal sections ----------
const C = [];
function add(...xs) { xs.flat().forEach((x) => C.push(x)); }

const TOC_PAGES = { "1. Introduction": 6, "2. System overview": 7, "3. Users, roles and access": 9, "4. Functional description": 11, "5. Court data integration (NAPIX)": 16, "6. Case Assistant and SourceTrace": 18, "7. System architecture": 20, "8. Data design": 22, "9. Security": 24, "10. Non-functional characteristics": 26, "11. Deployment and operations": 27, "12. Quality assurance": 28, "13. Status, variations from the plan and planned enhancements": 29, "Annexure A. Scheduled jobs": 31, "Annexure B. Functions": 32, "Annexure C. Court APIs": 35, "Annexure D. Glossary": 36 };
function documentControl() {
  add(H1("Document control"));
  add(table(["Version", "Date", "Description"], [["1.0", "27 October 2026", "First issue for submission: product overview, requirements and design of the system as built, security, operations and planned enhancements."], ["1.1", "27 October 2026", "Data collection console (first part) in service; the local-model Case Assistant approved as a variation from the plan; status figures and planned enhancements brought up to date."], ["1.2", "28 October 2026", "Session time-out, the next-hearing highlight, the Case Assistant’s local model (first part) and search and sort in lists (first round) in service; sign-in session rules corrected; status figures of 28 October 2026; Case Assistant polish and the next hearing shown directly from the latest court order added as planned enhancements."], ["1.3", "28 October 2026", "Case Assistant polish built: Enter sends a question, six quick facts answered from the court record held for the case without the AI, sources opened from their reference, fewer repeated answers; a variation from the plan added for the quick facts."]], [1400, 2200, CW - 3600]));
  add(H3("Contents"));
  [
    "1. Introduction", "2. System overview", "3. Users, roles and access", "4. Functional description", "5. Court data integration (NAPIX)",
    "6. Case Assistant and SourceTrace", "7. System architecture", "8. Data design", "9. Security", "10. Non-functional characteristics",
    "11. Deployment and operations", "12. Quality assurance", "13. Status, variations from the plan and planned enhancements",
    "Annexure A. Scheduled jobs", "Annexure B. Functions", "Annexure C. Court APIs", "Annexure D. Glossary",
  ].forEach((t) => add(new Paragraph({ spacing: { after: 60 }, tabStops: [{ type: "right", position: CW, leader: "dot" }], children: [new TextRun({ text: t, font: FONT }), new TextRun({ text: "	" + (TOC_PAGES[t] ?? ""), font: FONT })] })));
}

function s1() {
  add(H1("1. Introduction"));
  add(H2("1.1 Purpose"));
  add(P("This document describes the Assam State Litigation Management System (ASLMS): what it does, who uses it, how it is built, how it protects data, and how it is operated. It is written for submission to the Government of Assam and for the officials, reviewers and technical teams who will approve, host and use the system."));
  add(H2("1.2 Scope"));
  add(P("The document covers the system as built on 28 October 2026: the web portal, the application server, the background data collection from the Gauhati High Court, the database and document store, notifications, the Case Assistant in its preview form, and the monitoring and backup arrangements. Enhancements that are approved but not yet built are listed in section 13."));
  add(H2("1.3 Audience"));
  add(table(["Reader", "Most relevant sections"], [
    ["Approving authorities and department heads", "The brochure pages, 2, 3, 4 and 13"],
    ["Department administrators and nodal officers", "3, 4 and Annexure B"],
    ["Hosting and IT teams (State Data Centre)", "7, 9, 10, 11 and Annexure A"],
    ["Security and audit reviewers", "8, 9 and 12"],
  ], [4200, CW - 4200]));
  add(H2("1.4 References"));
  add(B("Legal Case Monitoring Portal: the agreed plan, the source of truth for the system’s scope."));
  add(B("eCourts NAPIX High Court API specifications issued by the e-Committee, Supreme Court of India, and the gateway documentation for the subscribed APIs."));
  add(B("ASLMS database standard and schema design, approved 29 September 2026."));
  add(B("ASLMS operations runbook (installation, upgrade, backup, restore, monitoring)."));
  add(B("ASLMS process workflows: how the system handles data, step by step."));
  add(H2("1.5 Conventions"));
  add(P("Times are Indian Standard Time. “The court” means the Gauhati High Court. Terms are explained in Annexure D."));
}

function s2() {
  add(H1("2. System overview"));
  add(H2("2.1 Background"));
  add(P("An earlier system collected case information by reading the court’s public website. It proved the value of a central record but depended on web pages that change without notice, and it served a limited number of departments. Access to the official eCourts APIs (NAPIX) has since been approved. ASLMS is a new system built on that official source, for every department of the State."));
  add(H2("2.2 Objectives"));
  add(N("Give every department a single, reliable place to find and track its cases before the Gauhati High Court.", "obj"));
  add(N("Obtain court data only from the official interface, keep every answer as received, and keep it current automatically.", "obj"));
  add(N("Route each case to the department it belongs to by recommendation, with the department deciding by claiming it.", "obj"));
  add(N("Make sure no hearing or court direction is missed, through alerts, calendars and next dates read from orders.", "obj"));
  add(N("Keep an accountable record of how each case is handled inside government: file movement, notes, documents and decisions.", "obj"));
  add(N("Give State oversight and auditors a complete, read-only view.", "obj"));
  add(H2("2.3 Principles the system never breaks"));
  add(table(["Principle", "What it means in practice"], [
    ["Recommend and claim", "The system only recommends a case to a department. A case belongs to a department only after a person in that department claims it, and once claimed it never returns to the unclaimed pool."],
    ["One gateway to the court", "Every call to the court goes through one integration component that handles encryption, the access token, retries and the hourly allowance, and logs every call. A failed call is recorded, never lost."],
    ["A master switch", "Court data collection is off unless an operator switches it on when the services start."],
    ["Every court answer kept", "Each answer is stored exactly as received, and every field also has a defined place in the database."],
    ["No made-up identifiers", "A CNR always comes from the court. A case known only by its number is provisional until the court confirms its CNR."],
    ["Visibility on the server", "The server decides what each person may see, for every request. Hiding something on screen is never the protection."],
    ["Notes are append-only", "A note is never edited or deleted. A correction is a new note linked to the original."],
    ["No deletion of legal records", "Cases, orders, documents and notes are kept. Documents can be archived, not deleted. Offices are deactivated, not deleted."],
    ["Everything significant audited", "Ownership decisions, file movements, notes, uploads, user and configuration changes, court searches and exports write an audit record."],
    ["No cloud AI. AI only through SourceTrace or, until it is available, a local model on Government servers", "No cloud AI service or cloud model, and no AI runtime inside ASLMS itself; the system refuses to start if one is found or a cloud model is configured. Only court orders and court filings may ever go to SourceTrace, never notes or internal documents. The local model reads one case\’s internal records only after the officer switches them on in that case\’s Assistant tab."],
  ], [2600, CW - 2600], { boldFirst: true }));
  add(H2("2.4 The system in context"));
  add(P("People use ASLMS through a web browser. ASLMS runs on government servers and connects to the following outside services:"));
  add(table(["Outside service", "Purpose", "Direction"], [
    ["NAPIX (eCourts, Gauhati High Court)", "Cause lists, case records, status, orders, searches and reference lists", "ASLMS calls out; encrypted"],
    ["Government e-mail relay", "Sign-in codes, alerts and the daily digest", "ASLMS sends"],
    ["SourceTrace (in-house AI service)", "Case Assistant answers from court orders and filings", "Prepared; connects when its API documentation is available"],
    ["Local model (Ollama)", "Case Assistant answers written by a local AI model on the ASLMS host or a Government server, until SourceTrace is connected", "Built; switched on by a setting, never a cloud model"],
  ], [3000, 4038, 2600]));
}

function s3() {
  add(H1("3. Users, roles and access"));
  add(H2("3.1 Offices, logins and memberships"));
  add(B("**Offices** form a tree that follows the government hierarchy: the State, then departments, then directorates and units. Offices are deactivated, never deleted."));
  add(B("**A login** belongs to one person and is identified by e-mail. The Super Administrator may create a login before its office is decided; such a login can sign in but sees nothing until it is placed in an office or named head of a department."));
  add(B("**A membership** places a login in one office with a designation (from a State-wide list) and a user type. One person can hold several memberships, for example in two departments, each with its own type."));
  add(B("Each department has one head and at most one department administrator. There is one Super Administrator for the State."));
  add(B("The head of a new department is chosen from existing logins. A change of head is proposed by the department administrator and approved by the Super Administrator through an administrative ticket."));
  add(B("When a person leaves an office, every case assigned to them and every file they hold is handed to a named officer first, in one recorded step."));
  add(H2("3.2 User types"));
  add(P("There are ten user types. Each type has a default set of functions; the Super Administrator can change the defaults of a type and grant or withdraw single functions for a person. The full list of the 51 functions is in Annexure B."));
  add(table(["User type", "Default role"], ref.roles.map((r) => [r.label, r.description]), [2800, CW - 2800], { boldFirst: true }));
  add(H2("3.3 Delegation"));
  add(P("A department administrator can create users and grant functions only inside their own department, only for officer, directorate, counsel and reviewer types, and only functions they hold themselves. Every grant is audited."));
  add(H2("3.4 Who can see which case"));
  add(P("For every request the server works out the person’s reason to see the case. Without one, the case does not exist for that person: the answer is “not found”, not “forbidden”."));
  add(table(["Person", "Sees"], [
    ["Super Administrator, State oversight, central operator, Auditor", "Every case in the State, read-only except for the Super Administrator’s administrative functions."],
    ["Department head or administrator", "Cases owned or watched by the department, recommended to it, being transferred to it, and the unclaimed pool to claim from."],
    ["Department officer or directorate officer", "Cases assigned to them or their unit, and cases whose file is with them or their office."],
    ["Standing counsel", "Cases carrying their department’s counsel code on a cause list or among the advocates."],
  ], [3600, CW - 3600], { boldFirst: true }));
  add(P("Notes and documents carry their own visibility, chosen each time by the person who adds them:"));
  add(table(["Visibility", "Who sees it"], [
    ["Everyone on the case", "Everyone who can see the case, except standing counsel, who see only their own"],
    ["Shared with counsel", "Everyone on the case, including standing counsel"],
    ["Private to my office", "The office, the author, and the department’s head and administrator. State-wide readers see these only with the separate “See Private Records Too” function."],
  ], [2800, CW - 2800], { boldFirst: true }));
  add(P("Court records (orders and cause lists) are open to everyone who can see the case."));
}

function s4() {
  add(H1("4. Functional description"));
  add(P("This section describes each module of the portal as built."));

  add(H2("4.1 Dashboard"));
  add(P("The first screen after sign-in shows what needs the person’s attention, according to their memberships and functions: a headline of their work, upcoming hearings, cases with pending action and items needing attention. A department view adds recommendations awaiting review and the department’s hearings and overdue actions. The State dashboard shows one row per department with unclaimed cases, hearings and overdue actions. Dashboards read only the ASLMS database."));

  add(H2("4.2 Recommendation and claim"));
  add(P("When a cause list or a court record arrives, the matching engine scores the case for every department from these signals:"));
  add(table(["Signal", "Example", "Default weight"], [
    ["Standing counsel code on the cause list or among the advocates", "“SC, EDU”", "0.95"],
    ["Name pattern in a party name", "“Director of Secondary Education”", "0.80"],
    ["The department’s watchlist", "A CNR the department follows", "0.75"],
    ["A linked case the department owns", "The original case behind an appeal", "0.70"],
    ["Partial counsel code match", "A printed code that contains or is contained in a mapped code", "0.60"],
    ["Keyword in a party name", "“school”", "0.40"],
  ], [4600, 3238, 1800]));
  add(P("Signals combine, so several weak signals together make a stronger match. The score decides the result:"));
  add(table(["Score", "Result"], [
    ["0.85 and above", "**Strong recommendation**, with an alert to the department’s claimers"],
    ["0.50 to 0.85", "**Possible match**, listed for the department to review"],
    ["Below 0.50", "No recommendation; the case stays in the unclaimed pool"],
  ], [2600, CW - 2600]));
  add(P("The Super Administrator can change the weights and the two bands, with a reason and a full history. Department administrators keep their department’s counsel codes, keywords, name patterns and watchlist; a panel lists counsel codes seen on cause lists that no department has mapped yet. Recommendations are recalculated after every mapping change. The mapping lists (counsel codes, keywords, name patterns and the watchlist) can be searched and sorted, and the list of counsel codes recommended from cause lists reads every unmapped code in pages of 100, with its own search and sort."));
  add(H3("Acting on a recommendation"));
  add(B("**Review.** The case opens in a large window with its details, parties, hearings, orders, linked cases and the reasons behind the score. Everything is read from the ASLMS database; opening it makes no call to the court."));
  add(B("**Claim.** The department becomes the primary owner. The person may assign the case at the same time to a responsible unit and a dealing officer, and add a note. A claim closes other departments’ open recommendations for that case with a notice, and queues a fresh court record."));
  add(B("**Dismiss.** The engine never recommends the case to that department again."));
  add(B("**Suggest another department**, with a reason; that department is alerted."));
  add(P("A case another department has already claimed can be followed as a **watcher**. Ownership can move only by a **transfer** that the receiving department accepts. Inside the department, a case can be **assigned** to a unit and officer, or **taken over** by a colleague."));

  add(H2("4.3 Case inbox"));
  add(P("The case inbox brings a person’s work together in tabs: the cases they are working on, recommended cases, department cases, transfers, the unclaimed pool and cases sent by them. Each list has server-side filters (status, year, case type, bench, dates, stage and more) and shows due dates first. **Search Words** on the case lists narrow a list by the words typed; the search runs on the server and never widens what the person may see."));

  add(H2("4.4 Search"));
  add(P("Search has two parts. **Search ASLMS** reads only the ASLMS database: a CNR, an ASLMS reference or a case number is matched exactly, words are matched against parties and advocates, and a separate tab searches the text of orders and documents. **Search the High Court** is used deliberately, by people holding that function, by CNR, case number, filing number, party name or advocate name."));
  add(B("A case already held with its full record is answered from the database, with no court call and nothing counted against the person’s allowance."));
  add(B("A case held without its full record is updated in place, never duplicated."));
  add(B("Results with a valid CNR are stored and scored, so the next person finds them locally; results without a CNR are shown but never stored."));
  add(B("Each person may make 30 court searches an hour; every court search is audited."));

  add(H2("4.5 Case page"));
  add(P("The case page shows a summary header (case number, CNR, status, court and bench, next hearing, owner and who has the file) with an action rail, and tabs for Overview, Hearings, Orders, Documents, Notes, Timeline, Assistant and More (Parties, Linked cases, Custody and stage, Alerts, Details). Orders open inline with print and download. All of it is read from the ASLMS database; opening a case page never calls the court."));
  add(P("Every case has an ASLMS reference on the court’s code, for example ASLMS/GHC/CASE/2026/000280, alongside the court’s CNR."));

  add(H2("4.6 File movement (custody) and stages"));
  add(B("Whoever holds the file can **send** it to any officer, in any department, with a remark, a pending action (examine, reply, file, comply, parawise comments and others) and an optional due date."));
  add(B("The receiver is alerted. The holder gets “due soon” before the due date and “overdue” after it, which the department’s trackers also see."));
  add(B("The department head and administrator can **recall** the file. Moving the file never changes ownership, and every move is kept in the file’s history."));
  add(B("The case’s **stage** is set by a person from 24 stages (notice issued, reply filed, appeal, contempt and others). The system never sets a stage by itself."));

  add(H2("4.7 Notes"));
  add(B("The holder of the file writes drafts that become permanent when the file moves on; anyone else’s note is permanent at once."));
  add(B("Visibility is chosen every time. Up to five attachments, each virus-scanned."));
  add(B("A note is never edited or deleted. A correction is a new note linked to the one it supersedes. Each note records the author’s name, designation and office at the time."));

  add(H2("4.8 Orders and documents"));
  add(B("Court orders of every held case are downloaded automatically, stored with their date, and their text extracted for search."));
  add(B("Users can upload court filings (writ petitions, affidavits, replies, applications and others) and internal documents (parawise comments, instructions to counsel and others): PDF, Word or image, up to 20 MB."));
  add(B("The type is checked from the file’s content, not its name, and every file is virus-scanned before it is stored; an infected file is refused and the attempt audited."));
  add(B("Each document has its own visibility. Documents can be archived, never deleted. Downloads of uploaded files are audited."));

  add(H2("4.9 Hearings, next dates, alerts and calendar"));
  add(P("Hearing dates come from the court’s own next date, from cause-list listings, and from dates read in order text. A date read from an order is firm only when it equals the court’s own date or a listing; otherwise it is a suggestion that an officer confirms, rejects (with a replacement date) or enters by hand. Directions such as “list after four weeks” are counted from the order date and always shown for confirmation."));
  add(table(["Event", "Alert"], [
    ["Hearing within 7 days", "High; critical within 48 hours"],
    ["Listed for tomorrow (from the evening cause list)", "To the people working on the case"],
    ["New order; next date, status or bench changed; disposed", "To the owners and the people working on the case"],
    ["File received or recalled", "To the person concerned"],
    ["Action due soon or overdue", "High, then critical; also to the department’s trackers"],
    ["New note on a case", "To the people working on the case"],
    ["Strong recommendation or suggestion from another department", "To the department’s claimers"],
    ["Assigned, taken over, transfer requested or decided", "To the people concerned"],
    ["A next date to confirm", "To the officers working on the case"],
  ], [5000, CW - 5000]));
  add(P("Alerts appear in the portal’s bell. Critical alerts are e-mailed at once; the rest come in a daily digest at 08:00 that also lists the next seven days’ hearings. Each person sets their own preferences. E-mails carry case numbers, dates and the kind of alert, never note text or document names. **My calendar** shows a person’s hearings, due dates and dates to confirm; **department hearings** shows the whole department."));
  add(P("The next hearing is shown with one badge on the case page, the case lists and the dashboards: Today and Tomorrow in strong red, two to seven days in amber with the number of days, later dates as the date, and Date Passed, No Date Yet or Disposed in words. A date suggested from an order is outlined and labelled Suggested. The meaning is always given in words, never by colour alone."));

  add(H2("4.10 Cause list"));
  add(P("Any date and bench can be viewed in court order with the printed entries, each entry’s recommendation or owner, a Claim button, counts and filters, and the original list document. A list the court re-issues with different entries is kept as a new version, and every screen shows the current version."));

  add(H2("4.11 Case Assistant"));
  add(P("A person holding the Case Assistant function asks a question in words, within one of three scopes (this case, my cases, all court orders), and gets answers with every source cited by document, date, page and excerpt. An answer can be copied into a case note. Section 6 describes the privacy rules and the SourceTrace connection."));

  add(H2("4.12 Reports"));
  add(table(["Report", "Content"], [
    ["Pending cases", "By department, court, case type and age"],
    ["Hearings and disposals", "Over a chosen period"],
    ["Pending actions", "Pending and overdue actions by office"],
    ["Data health", "The daily data cycle, failed court calls and Case Assistant intake"],
  ], [2800, CW - 2800], { boldFirst: true }));
  add(P("Reports run for a department or, with the State function, across all departments, with scope, period and holding department chosen on screen. They can be exported to Excel and PDF; every export is audited."));

  add(H2("4.13 Administration"));
  add(B("**Offices:** departments, directorates and units in the government hierarchy, with their head; the State-wide list of designations."));
  add(B("**Users:** creation, memberships, designations, user types, single-function grants, sign-in on or off, password reset, and the head-change tickets."));
  add(B("**User types:** the matrix of functions for each type, changed only by the Super Administrator."));
  add(B("**Department mapping:** counsel codes with the unmapped-codes panel, keywords and name patterns, the watchlist, and the scoring weights and bands with their history."));

  add(H2("4.14 Data collection and system health"));
  add(P("The data collection console shows what the system holds and what is left to fetch, in tabs:"));
  add(B("**Overview:** honest counts of cause-list days, case records and orders across all collection work, two finish estimates (case records, and every order as well) worked out from the measured pace, a month-by-month table and a live refresh while collection runs."));
  add(B("**Collect Now:** collection on request, such as fetching a single case or a period."));
  add(B("**Automatic Collection:** load control (start, pause, resume and the collection order) through confirmation dialogs, the daily schedule in plain words, and the search by department names."));
  add(P("A tab for problems and fixes, immediate manual requests and an Update From the Court button follow (section 13.3). The failures and duplicates screens remain available."));
  add(P("The system health screen shows the state of each of the 17 court APIs from the call log, ten ASLMS services, and a live test of one court API that is limited, guarded and audited."));

  add(H2("4.15 Audit log"));
  add(P("The Super Administrator and the Auditor can search every audited action by person, case, office, action and date, newest first, and open each entry to see the values before and after. Links lead to the audit trail from each case, person and office page. Reading the audit log is not itself audited, and audit records cannot be changed."));
}

function s5() {
  add(H1("5. Court data integration (NAPIX)"));
  add(H2("5.1 The gateway"));
  add(P("All court data comes from the NAPIX APIs through one integration component; no other part of the system calls the court."));
  add(B("**Access token.** ASLMS signs in with its own credentials, kept only in the server’s protected configuration file, and receives a token valid for about 55 minutes, shared by every part of ASLMS and renewed before it expires. A rejected token is renewed once and the call repeated."));
  add(B("**Encryption.** Every request and answer is encrypted as the NAPIX specification requires."));
  add(B("**Retries.** A busy court server is tried up to three times with short pauses; work that still fails returns to the queue."));
  add(B("**Call log.** Every attempt is recorded: which API, when, how long, the result and error, and the person whose action caused it."));
  add(B("**Answers kept.** Every successful answer is stored exactly as received; order and cause-list documents go to the document store."));
  add(H2("5.2 The hourly allowance"));
  add(P("NAPIX allows ASLMS about 1,000 calls an hour. ASLMS detects when the window resets from its own call log and keeps a reserve so that people’s searches are not blocked by background work:"));
  add(table(["Calls left in the hour", "What may run"], [
    ["150 or more", "Everything, including the historical load and discovery"],
    ["100 to 149", "Only people’s requests and the daily cycle"],
    ["Fewer than 100", "Nothing from the queue; the worker waits for the reset"],
    ["Fewer than 50", "A person’s court search is refused with “try again shortly”"],
  ], [3000, CW - 3000]));
  add(P("At most six court calls run at a time for people’s requests; when all are busy a person waits up to 20 seconds and then sees “the court service is busy, try again shortly”, which is not counted against them."));
  add(H2("5.3 How a case enters the database"));
  add(P("A case arrives from a cause list, a person’s court search, department discovery (a weekly search by a department’s registered names), a department’s watchlist, or the historical load. Every path ends at one step that finds or creates the case and never creates a second copy. A case known only by its number from a cause list is created as provisional and a court lookup is queued; when the court confirms its CNR the provisional case receives it. The full court record then fills parties, advocates, acts, hearings, orders, applications, objections, transfers, writ details, linked cases and lower-court details, and every distinct version of the record is kept."));
  add(H2("5.4 How a held case stays current"));
  add(B("Cases not disposed: current status **every day** (250 cases per call), a full record **every Sunday** and **whenever the status changes**."));
  add(B("New orders found in the full record are downloaded in the background, their text read, and the owners alerted."));
  add(B("Disposed cases are refreshed monthly for a year after disposal; a case restored to pending rejoins the daily cycle."));
  add(B("Cause lists for today and tomorrow are re-checked in the evening and morning; a corrected list is kept as a new version."));
  add(B("A claim or an accepted transfer queues a fresh full record at once."));
  add(H2("5.5 Queue, priorities and failures"));
  add(P("All court work waits in one queue in priority order: reference lists, then the cause lists, then people’s requests and the daily status, then the full records, the historical load, the weekly sweep, and finally order documents. Case details are completed before order documents, except for a case a person has asked for, which gets its orders at once."));
  add(P("A failed item is retried after 10 minutes, 1 hour, 6 hours, 24 hours and 72 hours, then marked failed and listed for an operator, who can queue it again. “Not found” and input errors are not retried. If the court keeps failing, the worker pauses for five minutes."));
  add(H2("5.6 What is not fetched, and retention"));
  add(B("Search rows without a valid CNR are shown but not stored, so no identifier is ever made up."));
  add(B("Show Business is used only for the system health test; Act Details, Neutral Citation and Advocate Bar Registration are not used."));
  add(B("Nothing is deleted except the call log, which is kept for two years. Cases, orders, documents, notes, the audit log and every answer as received are kept permanently."));
  add(P("The schedule of all jobs is in Annexure A, and the APIs used in Annexure C."));
}

function s6() {
  add(H1("6. Case Assistant and SourceTrace"));
  add(P("All AI in ASLMS goes through the Case Assistant’s connector interface. SourceTrace, the Government’s in-house retrieval-augmented generation service, is the intended AI. Until it is available, the owner has allowed (27 October 2026) one alternative for Case Assistant questions only: a local AI model served by Ollama on the ASLMS host or a server the Government controls, reached over the network. No cloud AI service or cloud model is used, no AI runtime runs inside ASLMS itself, and the system refuses to start if one is found or a cloud model is configured."));
  add(H2("6.1 What is sent, and what never is"));
  add(table(["May be sent to SourceTrace", "Never sent"], [
    ["Court orders and judgments, with their case details", "Case notes and their attachments"],
    ["Court filings uploaded by users, with their case details", "Internal and administrative documents"],
    ["", "File remarks, drafts, cause-list files and department uploads kept private"],
  ], [CW / 2, CW / 2]));
  add(P("The rule is enforced in three places, including the database. Ingestion records are append-only, with automatic retries and a screen listing failures."));
  add(P("The local model follows its own, narrower rule. By default, in every scope, it reads court information only: court orders, the court filings the officer may open, and the case details and hearings. On a case’s Assistant tab, and only there, the officer may press “Include This Case’s Internal Records”; from then on, in that conversation only, the model also reads that case’s saved notes, file movement with remarks, pending actions and department documents that the officer may open on the case page. Drafts are never read, another case’s records are never read, the switch is recorded in the audit log, and it cannot be switched off within the conversation."));
  add(H2("6.2 Current status: preview mode and the local model"));
  add(P("The Case Assistant screens, conversations, scopes, citations and privacy rules are built. The SourceTrace API documentation is awaited, so the connector to the real service is not yet built. In development and test, a preview mode answers by full-text search over the stored court text on the ASLMS server and shows the matching passages with the line “Preview: passages found in the court records, not an AI answer.” Nothing leaves the server. Preview mode is refused in production."));
  add(P("The local-model mode is built and allowed in production as the fallback until SourceTrace is connected. ASLMS finds the passages and records itself and gives them to the model as numbered sources; the model only writes the answer. Every sentence must cite its source; the server removes references to sources that were not given, and an answer with no valid reference is replaced by a fixed line. Each answer shows which sources were court records and which were internal, and the text that was given to the model."));
  add(P("Pressing Enter sends a question; Shift and Enter start a new line. Sources are not listed under an answer: each reference in the text, such as S1, opens that source in a dialog with its excerpt and a link to open it, and a Sources button opens the full list. The model is given the officer’s earlier questions in the conversation, not its own earlier answers, so that it answers the new question instead of repeating itself; a check command measures how much answers repeat."));
  add(P("On a case’s Assistant tab, six quick facts are answered straight from the court record held for the case, without the AI: the next hearing, the parties, the advocates, the status, the date of the last order and the bench. They are recognised only when the whole question is one of a fixed set of English forms, such as “when is the next date” or “who are the parties”; any other question goes to the AI. A quick fact is marked “From the Case Record”, cites the case details as its source, gives the same values as the case page, and is stored and audited like any answer. This is a variation from the plan (section 13.2)."));
  add(H2("6.3 Privacy rules"));
  add(B("Court information from NAPIX is open to every Case Assistant user. A cited order of a case the person cannot open is shown on a read-only court-record page with public facts only, never the owner, notes, file or documents; each opening is audited."));
  add(B("Department uploads, court filings included, appear only for people who may already see that document."));
  add(B("Conversations are private to the person who held them; no administrator or auditor can read them."));
  add(B("An answer that drew on an internal record the person can no longer open is hidden when read again."));
  add(B("Every question, answer and court-record opening writes an audit record with lengths, fingerprints and identifiers, never the text."));
  add(B("Each user may ask 30 questions an hour, one at a time."));
  add(H2("6.4 Approved alternative: a local model on Government machines"));
  add(P("Because SourceTrace is not yet available, the owner approved on 27 October 2026 a local model, served by Ollama on the ASLMS host or another Government server, as the Case Assistant’s answering engine until SourceTrace is connected. It is allowed in production and recorded as a variation from the plan (section 13.2). The first part is in service; the second, questions about the officer’s own work from the Assistant page, is planned."));
  add(table(["Rule", "How it works"], [
    ["Nothing leaves Government machines", "The model runs locally; a cloud model name or address stops the system from starting, and in production the model must be on a private address."],
    ["Court information by default", "In every scope the model reads only court information: orders, permitted court filings, and case details and hearings."],
    ["Internal records only when switched on", "On a case’s own page, the officer may switch on “Include This Case’s Internal Records”. Only then, and only for that case, the model also reads its notes, file movement and department documents that the officer may see. Drafts are never read. Switching on is audited and marked on the conversation."],
    ["Sources checked", "ASLMS picks the passages; the model writes only from them and must cite them. The server checks every citation and withholds an answer without a valid source. Each source opens from its reference in the answer, and the full list from the answer’s Sources button."],
    ["My work questions (planned)", "From the Assistant page, questions about the officer’s own work (pending actions, due dates, hearings, alerts, new orders) are answered from the same lists the portal shows, never from note contents."],
    ["SourceTrace unchanged", "SourceTrace keeps the plan’s rule: court orders and court filings only."],
  ], [2800, CW - 2800], { boldFirst: true }));
  add(P("The default model is qwen3.5:4b, which runs on a graphics card with 8 GB of memory and answers in a few seconds; a larger model can be set for the pilot server. The assistant informs and never acts: it cannot send files, change stages or write notes."));
}

function s7() {
  add(H1("7. System architecture"));
  add(H2("7.1 Layers"));
  add(table(["Layer", "Components"], [
    ["Delivery", "The web portal with its own server-side layer that keeps sign-in tokens in secure cookies; the reverse proxy for encryption in transit, host-name checks and throttling"],
    ["Application", "The application programming interface: cases and search, ownership and inbox, custody and notes, documents, alerts and calendar, Case Assistant, reports, administration and audit, with visibility applied to every request"],
    ["Processing", "The cause-list document reader, the matching engine, the case tracker, order text extraction, next-date reading, alert generation and the e-mail dispatcher"],
    ["Integration", "The NAPIX gateway (encryption, token, retries, allowance, call log), the scheduler and the queue worker, and the SourceTrace connector interface"],
    ["Data", "The PostgreSQL database with connection pooling, the document store, and full-text search over cases, orders and documents"],
    ["Operations", "Backups with a weekly restore check, the virus scanner, monitoring, alerting and dashboards"],
  ], [2000, CW - 2000], { boldFirst: true }));
  add(H2("7.2 Technology"));
  add(table(["Component", "Technology"], [
    ["Web portal", "Next.js (React), server-side layer for sessions"],
    ["Application server", "Python 3.11+, FastAPI"],
    ["Background jobs and scheduling", "Celery with Redis; a dedicated queue worker for court data"],
    ["Database", "PostgreSQL 16, with PgBouncer for connection pooling in transaction mode"],
    ["Document store", "Server file storage, each file named by its content fingerprint and linked from the database"],
    ["Schema changes", "Alembic migrations, applied only through an explicit, backed-up upgrade step"],
    ["Virus scanning", "ClamAV"],
    ["Reverse proxy", "nginx, with TLS"],
    ["Monitoring", "Prometheus, Alertmanager, Grafana, Flower and exporters for the database, Redis, PgBouncer and ASLMS operations"],
    ["Deployment", "Docker containers with Docker Compose"],
    ["AI", "SourceTrace through its API when connected; until then, optionally, a local model (Ollama) on the ASLMS host or a Government server"],
  ], [3000, CW - 3000], { boldFirst: true }));
  add(H2("7.3 Services"));
  add(table(["Service", "Role"], [
    ["proxy", "The only published service: TLS, host-name check, body limits, per-address throttling"],
    ["web", "The portal"],
    ["api", "The application programming interface"],
    ["worker", "The court data queue"],
    ["scheduler", "The timed jobs (Annexure A)"],
    ["init", "Start-up checks, database role passwords and reference data; then exits"],
    ["migrate", "The explicit upgrade step, with a backup first"],
    ["backup", "Database dumps, the document store mirror, retention and the weekly restore check"],
    ["postgres, pgbouncer, redis", "Database, connection pooling, token and message store"],
    ["clamav", "Virus scanning of every upload"],
    ["monitoring services", "Prometheus, Alertmanager, Grafana, Flower and the exporters"],
  ], [2800, CW - 2800], { boldFirst: true }));
  add(H2("7.4 Network separation"));
  add(B("Only the reverse proxy is reachable from the office network, on ports 443 and 80 (80 only redirects to 443)."));
  add(B("The proxy can reach only the portal; it cannot reach the application server, the database or Redis."));
  add(B("The portal and the application server share a separate network; the application server trusts forwarded addresses only from the portal."));
  add(B("The database, pooler, Redis and virus scanner sit on an internal network with the back-end services."));
  add(B("Monitoring screens are published on the host’s loopback only and opened through a secure tunnel."));
  add(B("Outbound access is limited to the NAPIX gateway, the mail relay and the virus-signature servers."));
}

function s8() {
  add(H1("8. Data design"));
  add(H2("8.1 Principles"));
  add(B("Built new from an approved database standard and schema design; the database started empty and is filled only from the court’s official data, user actions and department discovery."));
  add(B("Every table has a time-ordered unique key; records people refer to carry a readable reference number."));
  add(B("Code sets (case types, stages, user types, functions and others) live in reference tables, not in code."));
  add(B("Legal records are never deleted; events and the audit log are append-only."));
  add(B("Every field the court returns has a defined home in the schema, and each answer is also kept as received."));
  add(B("Schema changes are made only through new, reviewed migrations; an applied migration is never edited."));
  add(H2("8.2 Data groups"));
  add(table(["Group", "Contents"], [
    ["Reference", "Code sets and reference-number sequences"],
    ["Organisation and sign-in", "Offices, designations, logins, memberships, user types, functions, grants, devices, sessions and sign-in codes"],
    ["Court masters", "States, districts, benches, case types and acts from the court"],
    ["Cases", "Cases, parties, advocates, acts, hearings, applications, objections, transfers, writ details, links, lower-court details, status records and record versions"],
    ["Cause lists", "Lists by date, bench and version, and every entry as printed"],
    ["Ownership and matching", "Counsel codes, keywords, name patterns, watchlists, scoring settings and history, scores, recommendations, ownership, transfers and dismissals"],
    ["Workflow", "File movements, pending actions, stages and administrative tickets"],
    ["Notes and documents", "Append-only notes with attachments, orders, uploaded documents, extracted text and visibility"],
    ["Next dates, alerts and notifications", "Next dates from orders, alerts, notifications and preferences"],
    ["Case Assistant", "Conversations, ingestion records and their status"],
    ["Events and audit", "Case timeline events and the permanent audit log"],
    ["Integration and operations", "The court call log, answers as received, the fetch queue, job runs, failures and the data-load state"],
  ], [3000, CW - 3000], { boldFirst: true }));
  add(H2("8.3 Identifiers"));
  add(table(["Identifier", "Example", "Source"], [
    ["CNR", "GAHC010031562021", "Always from the court; never made up"],
    ["ASLMS case reference", "ASLMS/GHC/CASE/2026/000280", "Given by ASLMS on the court’s code; year and running number"],
    ["Provisional case", "Case type, number and year only", "From a cause-list line until the court confirms the CNR"],
  ], [2600, 3438, 3600], { boldFirst: true }));
}

function s9() {
  add(H1("9. Security"));
  add(H2("9.1 Sign-in and sessions"));
  add(B("Individual accounts only. Every sign-in needs the password and a six-digit code sent by e-mail, valid for 10 minutes, on every device."));
  add(B("Ten wrong passwords or codes lock the login for 15 minutes. Repeated attempts from one address are throttled at the proxy."));
  add(B("Passwords need at least 10 characters with a letter and a digit, and are stored only as a one-way hash (argon2id)."));
  add(B("At first sign-in the person must change the password and confirm their profile with a mobile number. A sign-in from a new device sends a notice."));
  add(B("Sign-in tokens are kept in secure, http-only cookies that page scripts cannot read; a person is signed out after 30 minutes without their own activity (clicks, typing, scrolling or moving between pages; background refreshes do not count), after a two-minute warning, and every session ends at most 12 hours after the code sign-in."));
  add(B("The server checks both limits on every request and every token renewal, so a session the server has ended cannot be continued from the browser; every session end, whether by sign-out, idle time or the 12-hour limit, writes an audit record."));
  add(B("Forgotten password: a code by e-mail; the answer is the same whether or not the address is registered."));
  add(B("Disabling a login ends its sessions; an administrator can sign a person out everywhere."));
  add(H2("9.2 Access control"));
  add(B("Role-based functions with per-person grants, and the State, department and directorate hierarchy, applied by the server to every request."));
  add(B("Per-note and per-document visibility; private records hidden from State-wide readers unless specifically granted."));
  add(B("A case a person may not see is answered as “not found”."));
  add(H2("9.3 Accountability"));
  add(B("An audit record for every significant action: sign-ins, ownership decisions, file movements, notes, uploads and downloads, user and access changes, configuration changes, court searches and exports."));
  add(B("Audit records and notes cannot be changed or deleted."));
  add(B("Every court call is logged with the person behind it, even when the call fails."));
  add(H2("9.4 Uploads"));
  add(B("Only PDF, Word and image files, checked by content; a 20 MB limit; a virus scan before anything is stored."));
  add(H2("9.5 Secrets and configuration"));
  add(B("Court credentials and every other secret are kept only in the server’s protected configuration file; never in the code, the database, the logs or the source repository."));
  add(B("Required secrets are checked at start-up; the system refuses to start in production without them."));
  add(B("Court credentials are never sent to the browser."));
  add(H2("9.6 Infrastructure hardening"));
  add(B("TLS for all browser traffic, with an internal certificate authority; host-name checking and request body limits at the proxy."));
  add(B("Separate database roles for the application, read-only monitoring and administration, with passwords stored as SCRAM verifiers."));
  add(B("Containers run as an unprivileged user, with no new privileges and all Linux capabilities dropped for the application services; logs are rotated."));
  add(B("Redis is password-protected and memory-only. Monitoring screens are not exposed to the network."));
  add(H2("9.7 Data protection"));
  add(B("All data is kept on government infrastructure; no public cloud service is used."));
  add(B("No case data is sent to any cloud AI service; only court orders and court filings may go to the in-house SourceTrace service, and the local model on Government servers reads one case’s internal records only after the officer switches them on (section 6)."));
  add(B("E-mails never contain note text or document names."));
  add(H2("9.8 Security review"));
  add(P("Every change is reviewed against these rules before it is accepted, and the source repository is scanned for secrets on every change (section 12). An independent security audit of the whole application, with proof-of-concept tests and a findings report, is scheduled before the pilot."));
}

function s10() {
  add(H1("10. Non-functional characteristics"));
  add(table(["Area", "Characteristic"], [
    ["Availability of court data", "Daily cycle before court hours; evening and morning cause-list checks; automatic retries over 72 hours; nothing lost on failure"],
    ["Capacity", "About 1,000 court calls an hour shared fairly by priority; six simultaneous court searches; 30 court searches and 30 Case Assistant questions per person per hour"],
    ["Responsiveness", "Case pages, dashboards and lists read only the ASLMS database and never wait for the court"],
    ["Recoverability", "Backups every six hours with a weekly automatic restore test; worst-case loss about six hours of user work"],
    ["Observability", "Metrics, 17 tested alert rules and three dashboards; alerts e-mailed to the operations team"],
    ["Usability", "Plain-language labels; layouts checked at phone, tablet and desktop widths (375, 768 and 1280 pixels); keyboard access; reduced motion respected"],
    ["Maintainability", "Layered design, reference data in tables, automated tests and continuous integration on every change"],
    ["Portability", "Docker containers; the same files serve a development machine and a State Data Centre virtual machine, including an offline host"],
  ], [2600, CW - 2600], { boldFirst: true }));
}

function s11() {
  add(H1("11. Deployment and operations"));
  add(H2("11.1 Host requirements"));
  add(table(["Resource", "Requirement"], [
    ["Processor and memory", "4 cores; at least 8 GB for the containers"],
    ["Disk", "200 GB free on SSD; backups on a second physical disk"],
    ["Inbound", "Ports 443 and 80 to the proxy only, from the office network"],
    ["Outbound", "The NAPIX gateway (HTTPS), the government mail relay, the virus-signature servers (or an offline mirror)"],
  ], [2800, CW - 2800], { boldFirst: true }));
  add(H2("11.2 Installation and upgrade"));
  add(N("Prepare the host and the protected configuration file; run the start-up checks.", "inst"));
  add(N("Build or load the container images (an offline host loads saved images).", "inst"));
  add(N("Apply the database schema through the explicit upgrade step, which takes a backup first and refuses an image built from different code.", "inst"));
  add(N("Start the services, with court data collection switched on by the operator for that run.", "inst"));
  add(N("Check the services, the page checks and the monitoring targets.", "inst"));
  add(H2("11.3 Backups and restore"));
  add(B("A database dump and a copy of the document store every six hours (00:30, 06:30, 12:30 and 18:30), each with a manifest of counts and checksums."));
  add(B("Retention: everything for 48 hours, daily for 14 days, weekly for 8 weeks, monthly for 12 months, and the last five pre-upgrade backups."));
  add(B("Every Sunday the latest backup is restored into a scratch database and compared."));
  add(B("A weekly encrypted off-machine copy, or the State Data Centre’s backup service."));
  add(H2("11.4 Monitoring"));
  add(P("Prometheus collects metrics every 30 seconds and keeps them for 30 days. Grafana shows the overview, the court data flow and the database. Alertmanager e-mails the operations team when a rule fires, for example the worker stopped, the court failing, the queue backing up, a backup missing, low disk, or the virus scanner down. Flower shows the scheduler’s tasks."));
  add(H2("11.5 Pilot go-live checklist"));
  add(B("Production start-up checks pass; only ports 443 and 80 reachable from another computer."));
  add(B("TLS checked from a pilot computer; throttling and the virus scanner checked through the proxy."));
  add(B("First backup and restore check passed, with the restore time recorded."));
  add(B("Connection pooling in the path and monitoring up, with a test alert received."));
  add(B("Data load counts and a sample check of 20 cases against the court recorded."));
  add(B("The government mail relay checked with a real sign-in."));
  add(B("The pilot department’s mapping entered and the owner’s browser checks completed."));
  add(B("The independent security audit completed and its findings closed."));
}

function s12() {
  add(H1("12. Quality assurance"));
  add(H2("12.1 How changes are made"));
  add(P("Every change starts as a written design that the owner approves before any building begins. It is then built, tested, reviewed against the project’s rules and the database standard, documented in the decisions log, and merged only when every check passes. A failing test always stops a merge."));
  add(H2("12.2 Automated testing"));
  add(table(["Suite", "Size (27 October 2026)", "Covers"], [
    ["Application server", "About 2,500 tests", "Services, interfaces, visibility, audit records, migrations up and down, court gateway behaviour with a scripted court"],
    ["Portal", "About 1,540 tests", "Screens, dialogs, wording rules, accessibility of controls"],
    ["Layout check", "Three widths", "Browser checks of key screens at 375, 768 and 1280 pixels"],
    ["Page check", "Every page", "Each portal page answers after a deployment"],
  ], [2400, 2400, CW - 4800], { boldFirst: true }));
  add(P("Tests never call the court; the court’s behaviour is simulated from recorded, decrypted samples. Each test run uses its own temporary database."));
  add(H2("12.3 Continuous integration"));
  add(P("Every change pushed to the source repository runs the policy checks, the secret scan, the application and portal test suites and a container build. Database upgrades are applied only after these checks pass."));
}

function s13() {
  add(H1("13. Status, variations from the plan and planned enhancements"));
  add(H2("13.1 Status"));
  add(P("The core and workflow functions of the plan are built and running in development, with the historical load of court data from 1 January 2025 complete for cause lists, all but 70 cases fetched with their full court records, and continuing for order documents. Deployment arrangements (proxy, backups, monitoring, connection pooling, continuous integration) are built and await the pilot checks."));
  add(P("On 28 October 2026 the cause lists of all 666 days in the collection period (from 1 January 2025) had been fetched; 83,205 cases had been found, 83,135 of them with their full court records; and 142,634 of 389,623 court orders had been stored. Order documents are being fetched at about 863 court calls an hour of the 1,000 the court allows, and the data collection console expects every order to be stored around 9 November 2026."));
  add(H2("13.2 Variations from the approved plan"));
  add(table(["Plan", "As built", "Reason"], [
    ["Migrate the data collected by the earlier system", "The database starts empty and is filled only from the official court interface, user actions and discovery", "Every record traceable to the official source; no inherited errors"],
    ["Search the database first, then the court automatically", "The person chooses to search the court; held cases are answered locally", "Court calls stay deliberate and within the hourly allowance"],
    ["Next dates read by SourceTrace", "Read by fixed rules and confirmed by a person; SourceTrace to assist when connected", "SourceTrace API documentation awaited"],
    ["Requests between offices", "Sending the file with a pending action and a due date", "One simpler mechanism covering the same need"],
    ["SMS for high-priority alerts", "In-app and e-mail; SMS refused until a gateway is provided", "No SMS gateway available yet"],
    ["One-time password at sign-in", "Six-digit code by e-mail at every sign-in", "Uses the government mail relay"],
    ["Case Assistant in phase 3", "Screens and rules built; preview mode until SourceTrace is connected", "Built early so the connector is the only remaining step"],
    ["All AI through SourceTrace", "Case Assistant answers written by a local model (Ollama) on Government servers until SourceTrace is connected; no cloud AI", "SourceTrace not yet available; owner’s decision of 27 Oct 2026"],
    ["Case Assistant answers by the AI", "Six quick facts on a case (next hearing, parties, advocates, status, last order date, bench) are answered from the court record held for the case, without the AI, with the same reference", "Owner, 28 Oct 2026: crisp answers to specific questions"],
    ["Notes and internal documents never sent to the AI", "Unchanged for SourceTrace. By default the local model reads court information only; it reads one case’s internal records (never drafts) only after the officer presses Include This Case’s Internal Records in that case’s Assistant tab (recorded in the audit log), and only what the officer may open", "Owner’s decision of 27 Oct 2026: officers work on their own case’s notes"],
  ], [2800, 3638, 3200]));
  add(H2("13.3 Planned enhancements"));
  add(table(["Enhancement", "Description"], [
    ["Session time-out", "Sign-out after 30 minutes without activity, with a two-minute warning, and a 12-hour limit on any session, enforced on the server, with an audit record for every session end (in service)"],
    ["Next hearing highlighted", "One date badge for the next hearing on the case page, case lists and dashboards, coloured by how soon: today and tomorrow, within a week, later, passed, none (in service)"],
    ["Case Assistant with a local model", "The approved local-model alternative described in section 6.4: first part in service; still to come: questions about the officer’s own work from the Assistant page"],
    ["Data collection console", "First part in service (overview, collect now, automatic collection); still to come: problems and fixes, immediate manual requests carried out at once"],
    ["Update from the court", "Update a case and fetch its orders at once from the case and claim screens, at priority, behind a function held by the Super Administrator by default"],
    ["Search and sort in lists", "First round in service: search and sort on the Department Mapping lists; Recommended From Cause Lists reading every unmapped counsel code in pages of 100; Search Words on the case lists. Searches and sorts run on the server and never widen what a person may see. Still to come (rounds 2 to 4): search and sort in the remaining lists"],
    ["Case Assistant polish", "Enter sends a question; six quick facts such as the next date and the parties answered from the court record; the sources of an answer shown in a dialog when a reference is clicked; fewer repeated answers (built; awaiting deployment)"],
    ["Next hearing from the latest court order", "The next hearing shown directly from the latest court order: dates given by the court shown without confirmation and not editable by anyone; a Report Wrong Next Date function; periods such as “list after three weeks” shown as an approximate date counted from the order (approved; planned, not built)"],
    ["SourceTrace connector", "The real connection for the Case Assistant and the ingestion of court orders and filings, when the API documentation is received"],
    ["Portal framework upgrade", "Upgrade of the web framework to its latest security release"],
    ["Text recognition of scanned orders", "Reading scanned orders through SourceTrace"],
    ["District courts", "District court cases through the NAPIX District Court API (plan phase 3)"],
    ["SMS", "High-priority alerts by SMS when a gateway is provided"],
  ], [3000, CW - 3000], { boldFirst: true }));
}

function annexA() {
  add(H1("Annexure A. Scheduled jobs"));
  add(table(["When (IST)", "Job", "What happens", "Calls the court"], [
    ["06:00 daily", "Court masters", "Refresh states, districts, benches, case types and acts", "Yes"],
    ["06:30 and 18:30 daily", "Cause lists", "Lists for yesterday, today and tomorrow; read each list document", "Yes"],
    ["18:30 (and 06:30 for today)", "Cause list re-check", "Ask again for lists held for today and tomorrow; keep a changed list as a new version", "Yes"],
    ["20:00 daily", "Status refresh", "Current status of every case not disposed, 250 per call", "Yes"],
    ["Every 5 minutes", "Order text", "Read the text of new orders and uploads", "No"],
    ["Every 5 minutes", "Next dates", "Read listing directions in order text", "No"],
    ["Every 5 minutes", "Alerts", "Turn new events into alerts", "No"],
    ["Hourly at :10", "Date alerts", "Hearing reminders, due and overdue actions", "No"],
    ["Every 2 minutes", "E-mail", "Send alert e-mails", "No"],
    ["08:00 daily", "Digest", "Each person’s daily summary e-mail", "No"],
    ["Every 15 minutes", "Rescore", "Recalculate recommendations after mapping or scoring changes", "No"],
    ["02:30 daily", "Disposed cases", "Monthly refresh of cases disposed within a year, up to 1,000 a night", "Yes"],
    ["03:00 daily", "Duplicates", "Find and merge duplicate case records", "No"],
    ["03:45 daily", "Call log purge", "Remove call-log rows older than two years", "No"],
    ["Saturday 02:00", "Discovery", "Search the court by departments’ registered names", "Yes"],
    ["Sunday 02:00", "Weekly sweep", "Full record of every case not disposed or never fully fetched", "Yes"],
    ["00:30, 06:30, 12:30, 18:30", "Backups", "Database dump and document store copy", "No"],
    ["Sunday 04:30", "Restore check", "Restore the latest backup into a scratch database and compare", "No"],
  ], [2200, 1800, 4238, 1400]));
}

function annexB() {
  add(H1("Annexure B. Functions"));
  add(P("The 51 functions that can be granted to user types and to individual people. The Super Administrator holds all of them."));
  const area = { access: "Access", admin: "Administration", alerts: "Alerts", assistant: "Case Assistant", audit: "Audit", cases: "Cases", custody: "File movement", dashboard: "Dashboard", documents: "Documents", next_dates: "Next dates", notes: "Notes", offices: "Offices", reports: "Reports", stages: "Stages", users: "Users" };
  add(table(["Area", "Function", "What it allows"], ref.functions.map((f) => [area[f.module] || f.module, f.label, f.description]), [1800, 2800, CW - 4600]));
}

function annexC() {
  add(H1("Annexure C. Court APIs"));
  add(table(["NAPIX API", "Used for", "When"], [
    ["Overview", "Connectivity check", "System health"],
    ["State, District and Bench masters", "Reference lists", "Daily at 06:00"],
    ["Case Type and Act masters", "Reference lists", "Daily at 06:00"],
    ["Cause List Bench", "Benches sitting on a date", "Daily, evening and morning"],
    ["Cause List Details", "The lists each bench published", "Daily, per bench"],
    ["Show Cause List", "The official list document, read entry by entry", "Daily, per list"],
    ["Search by CNR", "The full case record", "When first seen, weekly, on change, on request"],
    ["Current Status", "Next date, status and bench, 250 cases per call", "Daily at 20:00"],
    ["Show Order", "The order or judgment document", "When a new order appears"],
    ["Show Business", "Business of a hearing", "System health test only"],
    ["Search by Case Number", "Finding a case by type, number and year", "On a person’s search"],
    ["Search by Filing Number", "Finding a case by filing number", "On a person’s search"],
    ["Search by Party Name", "Finding cases by party name, one year per call", "On a person’s search; weekly discovery"],
    ["Search by Advocate Name", "Finding cases by advocate, one year per call", "On a person’s search"],
  ], [3000, 3838, 2800], { boldFirst: true }));
  add(P("The access token is obtained from the gateway’s token service. Seventeen APIs in all are monitored on the system health screen."));
}

function annexD() {
  add(H1("Annexure D. Glossary"));
  add(table(["Term", "Meaning"], [
    ["ASLMS", "Assam State Litigation Management System"],
    ["NAPIX", "The National API Exchange through which eCourts publishes court data; ASLMS reads Gauhati High Court data through it"],
    ["CNR", "Case Number Record: the court’s unique 16-character case identifier"],
    ["Provisional case", "A case known only by its number, from a cause-list line, whose CNR the court has not yet confirmed"],
    ["Full court record", "The complete case data from Search by CNR: parties, advocates, acts, hearings, orders and more"],
    ["Cause list", "The court’s daily list of cases to be heard, per bench"],
    ["Recommendation", "The system’s suggestion, with a score, that a case belongs to a department"],
    ["Claim", "A department taking ownership of a case; only a person can do this"],
    ["Primary owner, watcher", "The department that owns a case, and other departments following it"],
    ["Assign", "Choosing the responsible unit and dealing officer for a claimed case inside the department"],
    ["File, custody", "Who currently holds the case to act on it"],
    ["Membership", "A person’s place in one office, with a designation and user type"],
    ["Function", "A single permission, such as “Claim Cases” or “Search the High Court”"],
    ["Counsel code", "The standing counsel code printed on a cause list, for example “SC, EDU”"],
    ["SourceTrace", "The Government’s in-house AI (retrieval-augmented generation) service for the Case Assistant"],
    ["Preview mode", "The Case Assistant’s development stand-in: text search over stored court records, with no AI; refused in production"],
    ["Ollama", "The software that serves the Case Assistant’s local AI model on the ASLMS host or a Government server, used until SourceTrace is connected"],
    ["Hourly allowance", "The number of court calls ASLMS may make per hour (about 1,000)"],
  ], [2600, CW - 2600], { boldFirst: true }));
}

documentControl(); s1(); s2(); s3(); s4(); s5(); s6(); s7(); s8(); s9(); s10(); s11(); s12(); s13();
annexA(); annexB(); annexC(); annexD();

// ---------- document ----------
const numberingCfg = (reference, format, text) => ({ reference, levels: [{ level: 0, format, text, alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 440, hanging: 300 } } } }, { level: 1, format: LevelFormat.BULLET, text: "–", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 880, hanging: 300 } } } }] });

const footer = new Footer({ children: [new Paragraph({
  border: { top: { style: BorderStyle.SINGLE, size: 4, color: LINE, space: 6 } },
  children: [
    new TextRun({ text: "ASLMS Software Documentation · Government of Assam · For official use", size: 16, color: MUTED, font: FONT }),
    new TextRun({ text: "\tPage ", size: 16, color: MUTED, font: FONT }),
    new TextRun({ children: [PageNumber.CURRENT], size: 16, color: MUTED, font: FONT }),
  ],
  tabStops: [{ type: "right", position: CW }],
})] });

const pageProps = { page: { size: { width: PAGE_W, height: PAGE_H, orientation: PageOrientation.PORTRAIT }, margin: { top: MARGIN, bottom: MARGIN, left: MARGIN, right: MARGIN } } };

const doc = new Document({
  creator: "Government of Assam",
  title: "ASLMS Software Documentation",
  description: "Assam State Litigation Management System: product overview, requirements and design, security and operations",
  styles: {
    default: { document: { run: { font: FONT, size: 21, color: INK } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true, run: { size: 34, bold: true, color: NAVY, font: FONT }, paragraph: { spacing: { before: 0, after: 240 }, outlineLevel: 0, border: { bottom: { style: BorderStyle.SINGLE, size: 12, color: GOLD, space: 6 } } } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true, run: { size: 26, bold: true, color: TEAL, font: FONT }, paragraph: { spacing: { before: 280, after: 120 }, outlineLevel: 1, keepNext: true } },
      { id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true, run: { size: 22, bold: true, color: NAVY, font: FONT }, paragraph: { spacing: { before: 200, after: 80 }, outlineLevel: 2, keepNext: true } },
    ],
  },
  numbering: { config: [
    numberingCfg("bullets", LevelFormat.BULLET, "•"),
    numberingCfg("steps", LevelFormat.DECIMAL, "%1."),
    numberingCfg("obj", LevelFormat.DECIMAL, "%1."),
    numberingCfg("inst", LevelFormat.DECIMAL, "%1."),
  ] },
  sections: [
    { properties: pageProps, children: cover() },
    { properties: pageProps, footers: { default: footer }, children: [...brochure(), ...C] },
  ],
});

Packer.toBuffer(doc).then((buf) => { fs.writeFileSync(process.argv[2] || "ASLMS_Software_Documentation.docx", buf); console.log("written"); });
