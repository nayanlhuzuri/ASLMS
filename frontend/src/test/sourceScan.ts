/**
 * A source scan over the portal's components with the TypeScript parser (design portal-names-and-labels, decisions 7
 * and 12): where a property is *shown*, as opposed to used as a key, a comparison, a lookup or a request field.
 *
 * A value is shown when it sits in
 * - a JSX child expression (`<td>{r.office_code}</td>`, `<strong>{n.kind_label}</strong>`),
 * - a `cell:` renderer of a `DataTable` column,
 * - the arguments of a `T.*` string builder,
 * - the value side of a fact-list pair whose first element is a `T.*` label (`[T.files.office, r.office_code]`).
 *
 * Inside those places the walk does not enter JSX attributes (`key`, `title`, `href`, `value`, `code`), object
 * literals (request bodies), conditions and comparisons, index lookups, the arguments of lookup and compare calls
 * (`get`, `find`, `filter`, `localeCompare`…; their receiver is walked) or the calls a guard allows (`officeName(`,
 * `serverLabel(`…).
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";

import ts from "typescript";

export const COMPONENTS = join(process.cwd(), "src", "components");

export interface Source {
  path: string;
  text: string;
}

export function componentSources(): Source[] {
  const out: Source[] = [];
  const walk = (dir: string) => {
    for (const name of readdirSync(dir)) {
      const full = join(dir, name);
      if (statSync(full).isDirectory()) walk(full);
      else if (name.endsWith(".tsx") && !name.endsWith(".test.tsx")) {
        out.push({ path: relative(COMPONENTS, full).replace(/\\/g, "/"), text: readFileSync(full, "utf-8") });
      }
    }
  };
  walk(COMPONENTS);
  return out;
}

export interface Shown {
  path: string;
  line: number;
  /** The line's text, trimmed, for the message and the allowlist patterns. */
  text: string;
  /** The property access as written (`r.office_code`). */
  access: string;
}

const LOOKUP_METHODS = new Set([
  "localeCompare",
  "startsWith",
  "endsWith",
  "includes",
  "indexOf",
  "filter",
  "find",
  "findIndex",
  "some",
  "every",
  "sort",
  "has",
  "get",
  "set",
  "delete",
  "add",
  "push",
  "encodeURIComponent",
  "toLowerCase",
  "toUpperCase",
]);
const COMPARISONS = new Set([
  ts.SyntaxKind.EqualsEqualsEqualsToken,
  ts.SyntaxKind.ExclamationEqualsEqualsToken,
  ts.SyntaxKind.EqualsEqualsToken,
  ts.SyntaxKind.ExclamationEqualsToken,
  ts.SyntaxKind.LessThanToken,
  ts.SyntaxKind.GreaterThanToken,
  ts.SyntaxKind.LessThanEqualsToken,
  ts.SyntaxKind.GreaterThanEqualsToken,
]);

function calleeName(call: ts.CallExpression): string | null {
  const e = call.expression;
  if (ts.isIdentifier(e)) return e.text;
  if (ts.isPropertyAccessExpression(e)) return e.name.text;
  return null;
}

function isTBuilder(call: ts.CallExpression): boolean {
  let e: ts.Expression = call.expression;
  while (ts.isPropertyAccessExpression(e)) e = e.expression;
  return ts.isIdentifier(e) && e.text === "T" && e !== call.expression;
}

function startsWithT(e: ts.Expression | undefined): boolean {
  if (!e) return false;
  let x: ts.Expression = e;
  if (ts.isCallExpression(x)) x = x.expression;
  while (ts.isPropertyAccessExpression(x)) x = x.expression;
  return ts.isIdentifier(x) && x.text === "T" && x !== e;
}

/**
 * Every place in `src/components` where a property whose name passes `matches` is shown. `allowedCalls`: callee names
 * whose arguments are a proper way to show it (`officeName`, `serverLabel`…). `receiver` (optional): only accesses
 * whose object, as written, passes it are counted.
 */
export function shownProperties(
  sources: Source[],
  matches: (name: string, receiver: string, path: string) => boolean,
  allowedCalls: ReadonlySet<string>,
): Shown[] {
  const found = new Map<string, Shown>();
  for (const src of sources) {
    const file = ts.createSourceFile(src.path, src.text, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
    const lines = src.text.split("\n");
    const report = (node: ts.PropertyAccessExpression) => {
      const pos = file.getLineAndCharacterOfPosition(node.getStart(file));
      const key = `${src.path}:${node.getStart(file)}`;
      if (!found.has(key)) {
        found.set(key, { path: src.path, line: pos.line + 1, text: (lines[pos.line] ?? "").trim(), access: node.getText(file) });
      }
    };
    const shownIn = (node: ts.Node): void => {
      if (ts.isJsxAttribute(node) || ts.isObjectLiteralExpression(node)) return;
      if (ts.isConditionalExpression(node)) {
        shownIn(node.whenTrue);
        shownIn(node.whenFalse);
        return;
      }
      if (ts.isBinaryExpression(node)) {
        if (COMPARISONS.has(node.operatorToken.kind)) return;
        if (node.operatorToken.kind === ts.SyntaxKind.AmpersandAmpersandToken) {
          shownIn(node.right);
          return;
        }
      }
      if (ts.isElementAccessExpression(node)) {
        shownIn(node.expression);
        return;
      }
      if (ts.isCallExpression(node)) {
        const name = calleeName(node);
        if (name && allowedCalls.has(name)) return;
        if (name && LOOKUP_METHODS.has(name)) {
          // `list.filter(Boolean)` shows the list: the receiver is walked, the lookup's arguments are not
          if (ts.isPropertyAccessExpression(node.expression)) shownIn(node.expression.expression);
          return;
        }
      }
      if (ts.isPropertyAccessExpression(node)) {
        const receiver = node.expression.getText(file).replace(/\?$/, "");
        if (matches(node.name.text, receiver, src.path)) report(node);
      }
      ts.forEachChild(node, shownIn);
    };
    const visit = (node: ts.Node): void => {
      if (ts.isJsxExpression(node) && node.expression && (ts.isJsxElement(node.parent) || ts.isJsxFragment(node.parent))) {
        shownIn(node.expression);
      } else if (
        ts.isPropertyAssignment(node) &&
        ts.isIdentifier(node.name) &&
        node.name.text === "cell" &&
        (ts.isArrowFunction(node.initializer) || ts.isFunctionExpression(node.initializer))
      ) {
        shownIn(node.initializer.body);
      } else if (ts.isCallExpression(node) && isTBuilder(node)) {
        node.arguments.forEach(shownIn);
      } else if (ts.isArrayLiteralExpression(node) && startsWithT(node.elements[0])) {
        node.elements.slice(1).forEach(shownIn);
      }
      ts.forEachChild(node, visit);
    };
    visit(file);
  }
  return [...found.values()].sort((a, b) => (a.path === b.path ? a.line - b.line : a.path.localeCompare(b.path)));
}

/** "file:line  text" lines for a failure message. */
export function describe(found: Shown[]): string {
  return found.map((f) => `${f.path}:${f.line}  ${f.text}`).join("\n");
}

/** The findings no allowlist entry covers: an entry is a file and a pattern that the line's text must contain. */
export function notAllowed(found: Shown[], allow: readonly (readonly [string, RegExp | string, string])[]): Shown[] {
  return found.filter(
    (f) => !allow.some(([path, pattern]) => path === f.path && (typeof pattern === "string" ? f.text.includes(pattern) : pattern.test(f.text))),
  );
}

/** Allowlist entries that cover nothing any more (stale). */
export function unusedAllow(found: Shown[], allow: readonly (readonly [string, RegExp | string, string])[]): string[] {
  return allow
    .filter(([path, pattern]) => !found.some((f) => path === f.path && (typeof pattern === "string" ? f.text.includes(pattern) : pattern.test(f.text))))
    .map(([path, pattern]) => `${path} ${String(pattern)}`);
}
