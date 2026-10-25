/**
 * The frontend wording guard (design case-workspace-admin, decision 6): "file" must not reach what users read in the
 * custody sense. Through the TypeScript compiler API it reads every string literal and template piece of
 * `src/lib/messages.ts` (object keys skipped) and the JSX text of `src/components/**`. A text containing `\bfiles?\b`
 * fails unless an allow-list entry explains it, and a deny-list phrase fails even then. The allow-list covers only the
 * uploaded or downloaded computer-file sense and the legal verb ("File in court", "to file their reply"); the reviewer
 * checks every entry. Internal names (`components/files/*`, the nav key `files`, query keys) are code, not text.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, resolve } from "node:path";

import ts from "typescript";
import { describe, expect, it } from "vitest";

const SRC = resolve(__dirname, "..");

const WORD = /\bfiles?\b/i;

/** [pattern, reason]: the computer-file sense and the legal verb only. */
export const ALLOW: [RegExp, string][] = [
  [/\bfile type/gi, "the type of an uploaded computer file"],
  [/\b(PDF|Word|Excel|JSON) files?\b/gi, "a computer file of that format"],
  [/\b(the|this) file (is larger|is empty|failed the virus scan|is already on the (case|ticket)|is uploaded)/gi, "an uploaded computer file"],
  [/\b(Attach (a )?new files?|(Up to|At most) (\d+|\$\{n\}) files?(\(s\))?)/gi, "files attached from disk"],
  [/\bNo text in the file\b/gi, "an uploaded computer file's text"],
  [/\bFile \(PDF, Word or image\)/gi, "the upload field"],
  [/\bOld Word files\b/gi, "a computer file format"],
  [/\bFile in court\b/gi, "the pending action: the legal verb"],
  [/\bto file (their|its|a|an|the|anything)\b/gi, "the legal verb (the court asks a party to file)"],
];

export const DENY: RegExp[] = [
  /file (is )?with/i,
  /hold(s|ing)? (this |the )?file/i,
  /send (the )?file/i,
  /recall(ing)? (the )?files?/i,
  /files? (received|recalled|holder|remark|moved|movement|due|overdue)/i,
  /files with/i,
  /department files/i,
];

export function offends(text: string): boolean {
  if (!WORD.test(text)) return false;
  if (DENY.some((d) => d.test(text))) return true;
  let rest = text;
  for (const [pattern] of ALLOW) rest = rest.replace(pattern, "");
  return WORD.test(rest);
}

/** String literals and template pieces of a file, object keys left out. */
function stringsOf(path: string): { line: number; text: string }[] {
  const source = ts.createSourceFile(path, readFileSync(path, "utf-8"), ts.ScriptTarget.Latest, true, ts.ScriptKind.TS);
  const out: { line: number; text: string }[] = [];
  const add = (node: ts.Node, text: string) =>
    out.push({ line: source.getLineAndCharacterOfPosition(node.getStart()).line + 1, text });
  const visit = (node: ts.Node) => {
    const parent = node.parent;
    const isKey = parent && ts.isPropertyAssignment(parent) && parent.name === node;
    if ((ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) && !isKey) add(node, node.text);
    else if (ts.isTemplateExpression(node)) {
      add(node, [node.head.text, ...node.templateSpans.map((sp) => sp.literal.text)].join("${n}"));
    }
    // import specifiers are module names, not text
    if (ts.isImportDeclaration(node)) return;
    ts.forEachChild(node, visit);
  };
  visit(source);
  return out;
}

/** The JSX text of a component file. */
function jsxTextOf(path: string): { line: number; text: string }[] {
  const source = ts.createSourceFile(path, readFileSync(path, "utf-8"), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const out: { line: number; text: string }[] = [];
  const visit = (node: ts.Node) => {
    if (ts.isJsxText(node) && node.text.trim()) {
      out.push({ line: source.getLineAndCharacterOfPosition(node.getStart()).line + 1, text: node.text.trim() });
    }
    ts.forEachChild(node, visit);
  };
  visit(source);
  return out;
}

function componentFiles(dir: string): string[] {
  const out: string[] = [];
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) out.push(...componentFiles(full));
    else if (name.endsWith(".tsx") && !name.endsWith(".test.tsx")) out.push(full);
  }
  return out;
}

describe("the wording guard", () => {
  it("checks itself", () => {
    expect(offends("Send file")).toBe(true);
    expect(offends("the file is with the Under Secretary")).toBe(true);
    expect(offends("Files with me")).toBe(true);
    expect(offends("Department files")).toBe(true);
    expect(offends("You hold this file.")).toBe(true);
    expect(offends("The file is larger than the limit.")).toBe(false);
    expect(offends("File in court")).toBe(false);
    expect(offends("Case received")).toBe(false);
    expect(offends("the PDF file is with you")).toBe(true);
  });

  it("finds no custody-sense 'file' in messages.ts", () => {
    const bad = stringsOf(join(SRC, "lib", "messages.ts")).filter((s) => offends(s.text));
    expect(bad).toEqual([]);
  });

  it("finds no custody-sense 'file' in the JSX text of the components", () => {
    const bad = componentFiles(join(SRC, "components")).flatMap((f) =>
      jsxTextOf(f)
        .filter((s) => offends(s.text))
        .map((s) => ({ file: f.slice(SRC.length + 1), ...s })),
    );
    expect(bad).toEqual([]);
  });
});
