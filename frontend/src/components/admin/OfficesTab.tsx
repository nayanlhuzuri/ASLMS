"use client";

import { useEffect, useState, type FormEvent } from "react";
import { api } from "@/lib/api";
import { OFFICE_KINDS } from "@/lib/labels";
import { isOperator } from "@/lib/roles";
import type { Me, Office } from "@/lib/types";
import { loadOffices } from "../shell/MeContext";
import { Button } from "../ui/Button";
import { Dialog, DialogButtons } from "../ui/Dialog";
import { Field, Select, TextInput } from "../ui/Field";
import { Card } from "../ui/Layout";
import { Pill } from "../ui/Pill";
import { Empty, ErrorState, Loading } from "../ui/States";
import { useToast } from "../ui/Toast";
import s from "./admin.module.css";
import { depth, OfficeSelect } from "./common";

function inScope(me: Me, o: Office): boolean {
  if (isOperator(me)) return true;
  const d = me.department;
  return !!d && (o.path === d.path || o.path.startsWith(`${d.path}/`));
}

export function OfficesTab({ me }: { me: Me }) {
  const toast = useToast();
  const [all, setAll] = useState<Office[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const writable = me.can_admin;
  const operator = isOperator(me);

  useEffect(() => {
    let alive = true;
    api
      .get<Office[]>("/offices", { include_inactive: true })
      .then((list) => {
        if (alive) setAll([...list].sort((x, y) => x.path.localeCompare(y.path)));
      })
      .catch((e: unknown) => {
        if (alive) setError(e instanceof Error ? e.message : "Could not load offices.");
      });
    return () => {
      alive = false;
    };
  }, [tick]);

  const reload = () => {
    setTick((t) => t + 1);
    void loadOffices(true);
  };

  const kinds = operator ? Object.keys(OFFICE_KINDS) : ["directorate", "section", "counsel_office"];
  const [f, setF] = useState({ code: "", name: "", kind: "directorate", parent_id: me.department?.id ?? "" });
  const [busy, setBusy] = useState(false);
  const [renaming, setRenaming] = useState<Office | null>(null);
  const [newName, setNewName] = useState("");
  const [toggling, setToggling] = useState<string | null>(null);

  const add = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      await api.post("/offices", { code: f.code.trim().toUpperCase(), name: f.name.trim(), kind: f.kind, parent_id: f.parent_id || null });
      toast.success(`${f.name.trim()} added.`);
      setF({ ...f, code: "", name: "" });
      reload();
    } catch (err) {
      toast.error(err);
    } finally {
      setBusy(false);
    }
  };

  const toggle = async (o: Office) => {
    setToggling(o.id);
    try {
      await api.patch(`/offices/${o.id}`, { is_active: !o.is_active });
      toast.success(o.is_active ? `${o.name} deactivated.` : `${o.name} reactivated.`);
      reload();
    } catch (err) {
      toast.error(err);
    } finally {
      setToggling(null);
    }
  };

  const rename = async () => {
    if (!renaming || !newName.trim()) return;
    setBusy(true);
    try {
      await api.patch(`/offices/${renaming.id}`, { name: newName.trim() });
      toast.success("Office renamed.");
      setRenaming(null);
      reload();
    } catch (err) {
      toast.error(err);
    } finally {
      setBusy(false);
    }
  };

  if (error) return <ErrorState message={error} onRetry={reload} />;
  if (!all) return <Loading label="Loading offices" />;
  const parents = all.filter((o) => o.is_active && inScope(me, o));

  return (
    <div className={s.columns}>
      <Card className={s.main}>
        {all.length === 0 ? (
          <Empty title="No offices yet" />
        ) : (
          <ul className={s.tree} aria-label="Offices">
            {all.map((o) => (
              <li key={o.id} className={s.treeRow} style={{ paddingLeft: depth(o) * 24 }}>
                <div className={s.treeName}>
                  <span style={{ fontWeight: depth(o) === 0 ? 600 : 500, color: o.is_active ? undefined : "var(--muted)" }}>{o.name}</span>
                  <span className={s.treePath}>{o.path}</span>
                </div>
                <Pill tone="neutral">{OFFICE_KINDS[o.kind] ?? o.kind}</Pill>
                {!o.is_active ? <Pill tone="muted">Inactive</Pill> : null}
                {writable && inScope(me, o) ? (
                  <span style={{ display: "inline-flex", gap: 4 }}>
                    <Button
                      variant="link"
                      small
                      onClick={() => {
                        setRenaming(o);
                        setNewName(o.name);
                      }}
                    >
                      Rename<span className="sr-only"> {o.name}</span>
                    </Button>
                    <Button variant="link" small busy={toggling === o.id} onClick={() => toggle(o)}>
                      {o.is_active ? "Deactivate" : "Reactivate"}
                      <span className="sr-only"> {o.name}</span>
                    </Button>
                  </span>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </Card>
      {writable ? (
        <Card className={s.side} labelledBy="addoffice-h">
          <h2 id="addoffice-h">Add an office</h2>
          <p className={s.hint}>Directorates and sections sit under a department. Cases can be allotted to them after a claim.</p>
          <form className={s.form} onSubmit={add}>
            <Field label="Kind">
              <Select value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}>
                {kinds.map((k) => (
                  <option key={k} value={k}>
                    {OFFICE_KINDS[k]}
                  </option>
                ))}
              </Select>
            </Field>
            <OfficeSelect
              label="Parent office"
              value={f.parent_id}
              onChange={(v) => setF({ ...f, parent_id: v })}
              offices={parents}
              required={!operator || f.kind !== "department"}
              placeholder={operator ? "None (top level)" : "Choose the parent"}
            />
            <Field label="Code" hint="Short and unique, for example DSE.">
              <TextInput className="mono" required value={f.code} onChange={(e) => setF({ ...f, code: e.target.value })} />
            </Field>
            <Field label="Name">
              <TextInput required value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />
            </Field>
            <div>
              <Button type="submit" variant="primary" busy={busy}>
                Add office
              </Button>
            </div>
          </form>
        </Card>
      ) : null}
      <Dialog
        open={renaming !== null}
        onClose={() => setRenaming(null)}
        title="Rename office"
        description={renaming?.path}
        onSubmit={rename}
        footer={<DialogButtons submitLabel="Save" busy={busy} onCancel={() => setRenaming(null)} />}
      >
        <Field label="Name">
          <TextInput required value={newName} onChange={(e) => setNewName(e.target.value)} />
        </Field>
      </Dialog>
    </div>
  );
}
