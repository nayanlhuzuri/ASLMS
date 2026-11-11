/**
 * The office-name guard (design portal-names-and-labels, decision 7): an office code a reader sees goes through the
 * kit's `OfficeName` or `officeName(...)`. The scan fails when a property named `office_code`, `department_code`,
 * `*_office_code` or `*_department_code` is shown (a JSX child, a `DataTable` cell, a `T.*` string builder's argument,
 * a fact-list value). The code may stay in attributes (`key`, `rowKey`, `value`, `title`, `href`, `OfficeName`'s
 * `code`), request bodies, comparisons and lookups. The exceptions below name a file, a line pattern and the reason.
 */
import { describe as group, expect, it } from "vitest";

import { componentSources, describe, notAllowed, shownProperties, unusedAllow } from "@/test/sourceScan";

const CODE_PROPERTY = /^(?:\w+_)?(?:office|department)_code$/;
const ALLOWED_CALLS = new Set(["officeName", "nameOf"]);

/** [file, a pattern of the line, the reason]. */
const ALLOW: (readonly [string, RegExp | string, string])[] = [];

const SOURCES = componentSources();
const FOUND = shownProperties(SOURCES, (name) => CODE_PROPERTY.test(name), ALLOWED_CALLS);

group("office names, not codes (decision 7)", () => {
  it("shows every office code through OfficeName or officeName", () => {
    const bad = notAllowed(FOUND, ALLOW);
    expect(bad, `show these through <OfficeName code=… /> or officeName(…):\n${describe(bad)}`).toEqual([]);
  });

  it("keeps no stale exception", () => {
    expect(unusedAllow(FOUND, ALLOW)).toEqual([]);
    for (const [, , reason] of ALLOW) expect(reason.length).toBeGreaterThan(5);
  });

  it("catches a code shown as a JSX child, a cell and a string builder's argument", () => {
    const sample = [
      {
        path: "sample.tsx",
        text: [
          "const a = <td>{t.department_code}</td>;",
          'const b = <span className="mono">{r.office_code}</span>;',
          "const c = { key: \"x\", cell: (r) => r.holder_office_code };",
          "const d = <p>{T.inbox.fromTo(x.from_office_code, y)}</p>;",
          "const e = <OfficeName code={r.office_code} />;",
          "const f = <tr key={r.office_code}><td>{officeName(r.office_code, map)}</td></tr>;",
          "const g = <p>{r.office_code === mine ? \"Mine\" : \"Theirs\"}</p>;",
        ].join("\n"),
      },
    ];
    const hits = shownProperties(sample, (name) => CODE_PROPERTY.test(name), ALLOWED_CALLS).map((f) => f.line);
    expect(hits).toEqual([1, 2, 3, 4]);
  });
});
