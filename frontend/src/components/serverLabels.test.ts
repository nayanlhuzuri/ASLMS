/**
 * The server-label guard (design portal-names-and-labels, decision 12): a label that comes from the server is shown
 * through `serverLabel(…)` or `labelOf(…)`, which put it in Title Case (owner's option (a), K3). The scan fails when a
 * component shows `.kind_label`, `.doc_type_label`, `.pending_action_label`, `.reason_label`, `.role_label`,
 * `.group_label` or `.response_mode_label`, or the stage, timeline or attention label of the objects named below,
 * outside those calls. The lists of `useLabels` (kinds) and `useWorkflowCodes` / `useDocumentTypes` arrive in Title
 * Case from the hooks.
 */
import { describe as group, expect, it } from "vitest";

import { componentSources, describe, notAllowed, shownProperties, unusedAllow } from "@/test/sourceScan";

const LABEL_FIELDS = new Set([
  "kind_label",
  "doc_type_label",
  "pending_action_label",
  "reason_label",
  "role_label",
  "group_label",
  "response_mode_label",
]);

/** The files that read a stage, timeline or attention object, and the receivers whose `.label` / `.title` is a server label. */
const RECEIVERS: Record<string, { property: string; receiver: RegExp }[]> = {
  "case/CaseFrame.tsx": [{ property: "label", receiver: /^c\.stage$/ }],
  "inbox/rows.tsx": [{ property: "label", receiver: /^stage$/ }],
  "case/Overview.tsx": [{ property: "label", receiver: /^e$/ }],
  "case/Timeline.tsx": [{ property: "label", receiver: /^e$/ }],
  "workflow/CustodyTab.tsx": [{ property: "label", receiver: /^(cur|h)$/ }],
  "dashboard/Headline.tsx": [{ property: "title", receiver: /^(item|i|a|att)$/ }],
};

const ALLOWED_CALLS = new Set(["serverLabel", "labelOf"]);

/** [file, a pattern of the line, the reason]. */
const ALLOW: (readonly [string, RegExp | string, string])[] = [];

const SOURCES = componentSources();
const matches = (name: string, receiver: string, path: string) =>
  LABEL_FIELDS.has(name) || (RECEIVERS[path] ?? []).some((r) => r.property === name && r.receiver.test(receiver));
const FOUND = shownProperties(SOURCES, matches, ALLOWED_CALLS);

group("server labels in Title Case (decision 12)", () => {
  it("shows every server label through serverLabel or labelOf", () => {
    const bad = notAllowed(FOUND, ALLOW);
    expect(bad, `wrap these in serverLabel(…):\n${describe(bad)}`).toEqual([]);
  });

  it("keeps no stale exception and names files that exist", () => {
    expect(unusedAllow(FOUND, ALLOW)).toEqual([]);
    const paths = new Set(SOURCES.map((s) => s.path));
    expect(Object.keys(RECEIVERS).filter((p) => !paths.has(p))).toEqual([]);
  });

  it("catches a bare server label and lets a wrapped one through", () => {
    const sample = [
      {
        path: "sample.tsx",
        text: [
          "const a = <strong>{n.kind_label}</strong>;",
          "const b = { cell: (r) => r.pending_action_label };",
          "const c = <strong>{serverLabel(n.kind_label)}</strong>;",
          "const d = <p>{labelOf(list, x.code)}</p>;",
          "const e = <p key={r.reason_label}>{T.remarks.actionAsked(serverLabel(leg.pending_action_label))}</p>;",
        ].join("\n"),
      },
    ];
    expect(shownProperties(sample, matches, ALLOWED_CALLS).map((f) => f.line)).toEqual([1, 2]);
  });
});
