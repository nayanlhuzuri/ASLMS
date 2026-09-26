"use client";

import { useState, type FormEvent } from "react";
import { api } from "@/lib/api";
import { fmtNumber } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { CounselCode, Me, UnmappedCode } from "@/lib/types";
import { useOffices } from "../shell/MeContext";
import { Button } from "../ui/Button";
import { Check, Field, TextInput } from "../ui/Field";
import { Card, CardHead } from "../ui/Layout";
import { Pill } from "../ui/Pill";
import { Async, Empty } from "../ui/States";
import { DataTable } from "../ui/Table";
import { useToast } from "../ui/Toast";
import s from "./admin.module.css";
import { adminOffices, OfficeSelect, officeName } from "./common";

interface Draft {
  code: string;
  office_id: string;
  weight: string;
  is_generic_state: boolean;
  notes: string;
}

const EMPTY: Draft = { code: "", office_id: "", weight: "0.95", is_generic_state: false, notes: "" };

export function CodesTab({ me }: { me: Me }) {
  const toast = useToast();
  const { offices, byId } = useOffices();
  const codes = useApi<CounselCode[]>("/mapping/codes");
  const unmapped = useApi<UnmappedCode[]>("/mapping/unmapped-codes", { limit: 50 });
  const [draft, setDraft] = useState<Draft>(EMPTY);
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [removing, setRemoving] = useState<string | null>(null);
  const writable = me.can_admin;
  const choices = adminOffices(me, offices);

  const start = (d: Partial<Draft>, edit = false) => {
    setDraft({ ...EMPTY, office_id: me.department?.id ?? "", ...d });
    setEditing(edit);
    window.setTimeout(() => document.getElementById("code-input")?.focus(), 0);
  };

  const save = async (e: FormEvent) => {
    e.preventDefault();
    if (!draft.code.trim() || !draft.office_id) return;
    setBusy(true);
    try {
      await api.post("/mapping/codes", {
        code: draft.code.trim().toUpperCase(),
        office_id: draft.office_id,
        weight: Number(draft.weight) || 0.95,
        is_generic_state: draft.is_generic_state,
        notes: draft.notes.trim() || null,
      });
      toast.success(`Code ${draft.code.trim().toUpperCase()} saved. It applies to new cause lists and to pending cases at the next re-score.`);
      setDraft(EMPTY);
      setEditing(false);
      codes.reload();
      unmapped.reload();
    } catch (err) {
      toast.error(err);
    } finally {
      setBusy(false);
    }
  };

  const deactivate = async (c: CounselCode) => {
    setRemoving(c.id);
    try {
      await api.del(`/mapping/codes/${c.id}`);
      toast.success(`Code ${c.code} deactivated.`);
      codes.reload();
      unmapped.reload();
    } catch (err) {
      toast.error(err);
    } finally {
      setRemoving(null);
    }
  };

  return (
    <div className={s.columns}>
      <div className={s.main}>
        <Async state={codes} loadingLabel="Loading codes">
          {(list) =>
            list.length === 0 ? (
              <Card>
                <Empty title="No codes mapped yet">Map the standing counsel codes that appear in the cause lists to departments.</Empty>
              </Card>
            ) : (
              <DataTable
                caption="Standing counsel codes"
                rows={list}
                rowKey={(c) => c.id}
                columns={[
                  { key: "code", header: "Code in cause list", mono: true, render: (c) => <strong style={{ fontWeight: 500 }}>{c.code}</strong> },
                  { key: "office", header: "Mapped office", render: (c) => officeName(byId, c.office_id) },
                  { key: "weight", header: "Weight", num: true, render: (c) => c.weight.toFixed(2) },
                  {
                    key: "status",
                    header: "Status",
                    render: (c) =>
                      !c.is_active ? (
                        <Pill tone="muted">Inactive</Pill>
                      ) : c.is_generic_state ? (
                        <Pill tone="warning">Active · generic State code</Pill>
                      ) : (
                        <Pill tone="success">Active</Pill>
                      ),
                  },
                  { key: "notes", header: "Notes", render: (c) => c.notes || "-" },
                  {
                    key: "act",
                    header: "",
                    actions: true,
                    render: (c) =>
                      writable ? (
                        <span style={{ display: "inline-flex", gap: 4 }}>
                          <Button
                            variant="link"
                            small
                            onClick={() =>
                              start({ code: c.code, office_id: c.office_id, weight: String(c.weight), is_generic_state: c.is_generic_state, notes: c.notes ?? "" }, true)
                            }
                          >
                            Edit<span className="sr-only"> {c.code}</span>
                          </Button>
                          {c.is_active ? (
                            <Button variant="link" small busy={removing === c.id} onClick={() => deactivate(c)}>
                              Deactivate<span className="sr-only"> {c.code}</span>
                            </Button>
                          ) : null}
                        </span>
                      ) : null,
                  },
                ]}
              />
            )
          }
        </Async>
        <Card labelledBy="unmapped-h">
          <CardHead id="unmapped-h" title="Codes seen in cause lists but not mapped" />
          <p className={s.hint}>Most frequent first. Mapping a code makes the cases that carry it appear as recommendations.</p>
          <Async state={unmapped} loadingLabel="Loading unmapped codes">
            {(list) =>
              list.length === 0 ? (
                <Empty title="Every code seen so far is mapped" />
              ) : (
                <DataTable
                  bare
                  caption="Unmapped codes"
                  rows={list}
                  rowKey={(u) => u.code}
                  columns={[
                    { key: "code", header: "Code", mono: true, render: (u) => u.code },
                    { key: "seen", header: "Times seen", num: true, render: (u) => fmtNumber(u.seen) },
                    {
                      key: "act",
                      header: "",
                      actions: true,
                      render: (u) =>
                        writable ? (
                          <Button small onClick={() => start({ code: u.code })}>
                            Map<span className="sr-only"> {u.code}</span>
                          </Button>
                        ) : null,
                    },
                  ]}
                />
              )
            }
          </Async>
        </Card>
      </div>
      {writable ? (
        <Card className={s.side} labelledBy="addcode-h">
          <h2 id="addcode-h">{editing ? "Edit a code" : "Add a code"}</h2>
          <p className={s.hint}>Enter the code exactly as it appears in the advocate column of the cause list.</p>
          <form className={s.form} onSubmit={save}>
            <Field label="Code">
              <TextInput
                id="code-input"
                className="mono"
                required
                value={draft.code}
                readOnly={editing}
                onChange={(e) => setDraft({ ...draft, code: e.target.value })}
                placeholder="e.g. SC, EDU"
              />
            </Field>
            <OfficeSelect label="Department or directorate" value={draft.office_id} onChange={(v) => setDraft({ ...draft, office_id: v })} offices={choices} required />
            <Field label="Weight" hint="0 to 1. A counsel code is the strongest signal (0.95 by default).">
              <TextInput type="number" step="0.01" min={0} max={1} value={draft.weight} onChange={(e) => setDraft({ ...draft, weight: e.target.value })} />
            </Field>
            <Check
              label="Generic State code (for example PP, ASSAM): adds nothing to a score"
              checked={draft.is_generic_state}
              onChange={(e) => setDraft({ ...draft, is_generic_state: e.target.checked })}
            />
            <Field label="Notes (optional)">
              <TextInput value={draft.notes} onChange={(e) => setDraft({ ...draft, notes: e.target.value })} />
            </Field>
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
              <Button type="submit" variant="primary" busy={busy}>
                Save code
              </Button>
              <Button
                onClick={() => {
                  setDraft(EMPTY);
                  setEditing(false);
                }}
              >
                Cancel
              </Button>
            </div>
          </form>
        </Card>
      ) : null}
    </div>
  );
}
