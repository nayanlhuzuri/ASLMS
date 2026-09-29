"use client";

import { useState, type FormEvent } from "react";
import { api } from "@/lib/api";
import { humanize } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { Keyword, Me, Pattern } from "@/lib/types";
import { useOffices } from "../shell/MeContext";
import { Button } from "../ui/Button";
import { Field, Select, TextInput } from "../ui/Field";
import { Card, CardHead } from "../ui/Layout";
import { Async, Empty } from "../ui/States";
import { DataTable } from "../ui/Table";
import { useToast } from "../ui/Toast";
import s from "./admin.module.css";
import { adminOffices, OfficeSelect, officeName } from "./common";

function useRemove(after: () => void) {
  const toast = useToast();
  const [busy, setBusy] = useState<string | null>(null);
  const remove = async (path: string, id: string, label: string) => {
    setBusy(id);
    try {
      await api.del(`${path}/${id}`);
      toast.success(`${label} deactivated (kept for the record). A full re-score of pending cases has been queued.`);
      after();
    } catch (e) {
      toast.error(e);
    } finally {
      setBusy(null);
    }
  };
  return { busy, remove };
}

export function KeywordsTab({ me }: { me: Me }) {
  const toast = useToast();
  const { offices, byId } = useOffices();
  const patterns = useApi<Pattern[]>("/mapping/patterns");
  const keywords = useApi<Keyword[]>("/mapping/keywords");
  const writable = me.can_admin;
  const choices = adminOffices(me, offices);
  const defaultOffice = me.department?.id ?? "";

  const [p, setP] = useState({ office_id: defaultOffice, pattern: "", kind: "exact", weight: "0.8" });
  const [k, setK] = useState({ office_id: defaultOffice, keyword: "", weight: "0.4" });
  const [busyP, setBusyP] = useState(false);
  const [busyK, setBusyK] = useState(false);
  const rmP = useRemove(patterns.reload);
  const rmK = useRemove(keywords.reload);

  const addPattern = async (e: FormEvent) => {
    e.preventDefault();
    setBusyP(true);
    try {
      await api.post("/mapping/patterns", { office_id: p.office_id, pattern: p.pattern.trim(), kind: p.kind, weight: Number(p.weight) || 0.8 });
      toast.success("Name pattern added. A full re-score of pending cases has been queued.");
      setP({ ...p, pattern: "" });
      patterns.reload();
    } catch (err) {
      toast.error(err);
    } finally {
      setBusyP(false);
    }
  };

  const addKeyword = async (e: FormEvent) => {
    e.preventDefault();
    setBusyK(true);
    try {
      await api.post("/mapping/keywords", { office_id: k.office_id, keyword: k.keyword.trim(), weight: Number(k.weight) || 0.4 });
      toast.success("Keyword added. A full re-score of pending cases has been queued.");
      setK({ ...k, keyword: "" });
      keywords.reload();
    } catch (err) {
      toast.error(err);
    } finally {
      setBusyK(false);
    }
  };

  return (
    <div className={s.columns}>
      <div className={s.main}>
        <Card labelledBy="pat-h">
          <CardHead id="pat-h" title="Name patterns" />
          <p className={s.hint}>Party names that identify an office, such as &quot;Director of Secondary Education&quot;.</p>
          <Async state={patterns} loadingLabel="Loading patterns">
            {(list) =>
              list.length === 0 ? (
                <Empty title="No name patterns yet" />
              ) : (
                <DataTable
                  bare
                  caption="Name patterns"
                  rows={list}
                  rowKey={(r) => r.id}
                  columns={[
                    { key: "pattern", header: "Pattern", mono: true, render: (r) => r.pattern },
                    { key: "kind", header: "Match", render: (r) => humanize(r.kind) },
                    { key: "office", header: "Office", render: (r) => officeName(byId, r.office_id) },
                    { key: "weight", header: "Weight", num: true, render: (r) => r.weight.toFixed(2) },
                    {
                      key: "act",
                      header: "",
                      actions: true,
                      render: (r) =>
                        writable ? (
                          <Button variant="link" small busy={rmP.busy === r.id} onClick={() => rmP.remove("/mapping/patterns", r.id, "Pattern")}>
                            Deactivate<span className="sr-only"> {r.pattern}</span>
                          </Button>
                        ) : null,
                    },
                  ]}
                />
              )
            }
          </Async>
        </Card>
        <Card labelledBy="kw-h">
          <CardHead id="kw-h" title="Keywords" />
          <p className={s.hint}>Words in party names or the case record that point to an office. Weaker than a code or pattern.</p>
          <Async state={keywords} loadingLabel="Loading keywords">
            {(list) =>
              list.length === 0 ? (
                <Empty title="No keywords yet" />
              ) : (
                <DataTable
                  bare
                  caption="Keywords"
                  rows={list}
                  rowKey={(r) => r.id}
                  columns={[
                    { key: "kw", header: "Keyword", render: (r) => r.keyword },
                    { key: "office", header: "Office", render: (r) => officeName(byId, r.office_id) },
                    { key: "weight", header: "Weight", num: true, render: (r) => r.weight.toFixed(2) },
                    {
                      key: "act",
                      header: "",
                      actions: true,
                      render: (r) =>
                        writable ? (
                          <Button variant="link" small busy={rmK.busy === r.id} onClick={() => rmK.remove("/mapping/keywords", r.id, "Keyword")}>
                            Deactivate<span className="sr-only"> {r.keyword}</span>
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
        <div className={s.side}>
          <Card labelledBy="addpat-h">
            <h2 id="addpat-h">Add a name pattern</h2>
            <form className={s.form} onSubmit={addPattern}>
              <OfficeSelect label="Office" value={p.office_id} onChange={(v) => setP({ ...p, office_id: v })} offices={choices} required />
              <Field label="Pattern">
                <TextInput required value={p.pattern} onChange={(e) => setP({ ...p, pattern: e.target.value })} />
              </Field>
              <Field label="Match">
                <Select value={p.kind} onChange={(e) => setP({ ...p, kind: e.target.value })}>
                  <option value="exact">Exact name</option>
                  <option value="prefix">Name starts with</option>
                  <option value="regex">Regular expression</option>
                </Select>
              </Field>
              <Field label="Weight">
                <TextInput type="number" step="0.01" min={0} max={1} value={p.weight} onChange={(e) => setP({ ...p, weight: e.target.value })} />
              </Field>
              <div>
                <Button type="submit" variant="primary" busy={busyP}>
                  Add pattern
                </Button>
              </div>
            </form>
          </Card>
          <Card labelledBy="addkw-h">
            <h2 id="addkw-h">Add a keyword</h2>
            <form className={s.form} onSubmit={addKeyword}>
              <OfficeSelect label="Office" value={k.office_id} onChange={(v) => setK({ ...k, office_id: v })} offices={choices} required />
              <Field label="Keyword">
                <TextInput required value={k.keyword} onChange={(e) => setK({ ...k, keyword: e.target.value })} />
              </Field>
              <Field label="Weight">
                <TextInput type="number" step="0.01" min={0} max={1} value={k.weight} onChange={(e) => setK({ ...k, weight: e.target.value })} />
              </Field>
              <div>
                <Button type="submit" variant="primary" busy={busyK}>
                  Add keyword
                </Button>
              </div>
            </form>
          </Card>
        </div>
      ) : null}
    </div>
  );
}
