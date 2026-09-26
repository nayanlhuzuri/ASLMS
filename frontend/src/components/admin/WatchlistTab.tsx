"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";
import { api } from "@/lib/api";
import { fmtDate } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import { canWatch, isOperator } from "@/lib/roles";
import type { Me, Watch } from "@/lib/types";
import { useOffices } from "../shell/MeContext";
import { Button } from "../ui/Button";
import { Field, TextInput } from "../ui/Field";
import { Card } from "../ui/Layout";
import { Pill } from "../ui/Pill";
import { Async, Empty } from "../ui/States";
import { DataTable } from "../ui/Table";
import { useToast } from "../ui/Toast";
import s from "./admin.module.css";
import { OfficeSelect, officeName } from "./common";

export function WatchlistTab({ me }: { me: Me }) {
  const toast = useToast();
  const { departments, byId } = useOffices();
  const list = useApi<Watch[]>("/mapping/watchlist");
  const writable = canWatch(me);
  const operator = isOperator(me);
  const [cnr, setCnr] = useState("");
  const [reason, setReason] = useState("");
  const [office, setOffice] = useState("");
  const [busy, setBusy] = useState(false);
  const [removing, setRemoving] = useState<string | null>(null);

  const add = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      await api.post("/mapping/watchlist", { cnr: cnr.trim().toUpperCase(), reason: reason.trim() || null, office_id: operator ? office : null });
      toast.success("Added to the watchlist.");
      setCnr("");
      setReason("");
      list.reload();
    } catch (err) {
      toast.error(err);
    } finally {
      setBusy(false);
    }
  };

  const remove = async (w: Watch) => {
    setRemoving(w.id);
    try {
      await api.del(`/mapping/watchlist/${w.id}`);
      toast.success(`${w.cnr} removed from the watchlist.`);
      list.reload();
    } catch (err) {
      toast.error(err);
    } finally {
      setRemoving(null);
    }
  };

  return (
    <div className={s.columns}>
      <div className={s.main}>
        <Async state={list} loadingLabel="Loading the watchlist">
          {(rows) =>
            rows.length === 0 ? (
              <Card>
                <Empty title="The watchlist is empty">A watchlisted CNR is recommended to the department whenever it appears in a cause list.</Empty>
              </Card>
            ) : (
              <DataTable
                caption="Watchlist"
                rows={rows}
                rowKey={(w) => w.id}
                columns={[
                  {
                    key: "cnr",
                    header: "CNR",
                    mono: true,
                    render: (w) => (w.case_id ? <Link href={`/cases/${w.case_id}`}>{w.cnr}</Link> : w.cnr),
                  },
                  { key: "office", header: "Department", render: (w) => officeName(byId, w.office_id) },
                  { key: "reason", header: "Reason", render: (w) => w.reason || "-" },
                  { key: "added", header: "Added", render: (w) => fmtDate(w.created_at) },
                  { key: "status", header: "Status", render: (w) => <Pill tone={w.is_active ? "success" : "muted"}>{w.is_active ? "Active" : "Removed"}</Pill> },
                  {
                    key: "act",
                    header: "",
                    actions: true,
                    render: (w) =>
                      writable && w.is_active ? (
                        <Button variant="link" small busy={removing === w.id} onClick={() => remove(w)}>
                          Remove<span className="sr-only"> {w.cnr}</span>
                        </Button>
                      ) : null,
                  },
                ]}
              />
            )
          }
        </Async>
      </div>
      {writable ? (
        <Card className={s.side} labelledBy="addwatch-h">
          <h2 id="addwatch-h">Watch a case</h2>
          <form className={s.form} onSubmit={add}>
            {operator ? <OfficeSelect label="Department" value={office} onChange={setOffice} offices={departments} required /> : null}
            <Field label="CNR (CINO)" hint="16 characters, for example GAHC01xxxxxxYYYY.">
              <TextInput className="mono" required minLength={16} maxLength={16} value={cnr} onChange={(e) => setCnr(e.target.value.toUpperCase())} />
            </Field>
            <Field label="Reason (optional)">
              <TextInput value={reason} onChange={(e) => setReason(e.target.value)} />
            </Field>
            <div>
              <Button type="submit" variant="primary" busy={busy}>
                Add to watchlist
              </Button>
            </div>
          </form>
        </Card>
      ) : null}
    </div>
  );
}
