"use client";

import { useState, type FormEvent } from "react";
import { api } from "@/lib/api";
import { fmtDateTime } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { CaseCard, Office, Page, Recommendation, Transfer } from "@/lib/types";
import { CardList, caseNumber, TrackingCard } from "../case/CaseBits";
import { Button } from "../ui/Button";
import { Field, Select, TextInput } from "../ui/Field";
import { Pagination } from "../ui/Pagination";
import { Pill } from "../ui/Pill";
import { Async, Empty } from "../ui/States";
import { useToast } from "../ui/Toast";
import { DismissDialog } from "./DismissDialog";
import { ReasonDialog } from "./ReasonDialog";
import { RecommendationCard } from "./RecommendationCard";

const SIZE = 20;

interface Common {
  officeId?: string;
  canAct: boolean;
  onChanged: () => void;
}

function useClaim(officeId: string | undefined, after: () => void) {
  const toast = useToast();
  const [busyId, setBusyId] = useState<string | null>(null);
  const claim = async (c: CaseCard) => {
    setBusyId(c.id);
    try {
      await api.post(`/cases/${c.id}/claim`, { office_id: officeId ?? null });
      toast.success(`${caseNumber(c)} claimed. It is now tracked by your department.`);
      after();
    } catch (e) {
      toast.error(e);
    } finally {
      setBusyId(null);
    }
  };
  return { busyId, claim };
}

export function RecommendedPanel({
  officeId,
  canAct,
  onChanged,
  departments,
  band,
  page,
  setBand,
  setPage,
}: Common & {
  departments: Office[];
  band: string;
  page: number;
  setBand: (b: string) => void;
  setPage: (p: number) => void;
}) {
  const list = useApi<Page<Recommendation>>("/inbox/recommended", { office_id: officeId, band: band || undefined, page, size: SIZE });
  const refresh = () => {
    list.reload();
    onChanged();
  };
  const { busyId, claim } = useClaim(officeId, refresh);
  const [dismiss, setDismiss] = useState<{ rec: Recommendation; suggest: boolean } | null>(null);

  return (
    <>
      <div style={{ display: "flex", gap: 12, alignItems: "flex-end", flexWrap: "wrap" }}>
        <Field label="Match strength">
          <Select value={band} onChange={(e) => setBand(e.target.value)} style={{ minWidth: 220 }}>
            <option value="">All recommendations</option>
            <option value="high">Strong (0.85 and above)</option>
            <option value="medium">Possible (0.50 to 0.85)</option>
          </Select>
        </Field>
      </div>
      <Async state={list} loadingLabel="Loading recommendations">
        {(p) =>
          p.items.length === 0 ? (
            <Empty title="No recommendations waiting" center>
              New recommendations arrive with each day&apos;s cause lists. Cases below 0.50 stay in the unclaimed pool.
            </Empty>
          ) : (
            <>
              <CardList>
                {p.items.map((r) => (
                  <RecommendationCard
                    key={r.id}
                    rec={r}
                    canAct={canAct}
                    busy={busyId === r.case.id}
                    onClaim={() => claim(r.case)}
                    onDismiss={() => setDismiss({ rec: r, suggest: false })}
                    onSuggest={() => setDismiss({ rec: r, suggest: true })}
                  />
                ))}
              </CardList>
              <Pagination page={p.page} size={p.size} total={p.total} onPage={setPage} noun="recommendations" />
            </>
          )
        }
      </Async>
      <DismissDialog
        caseId={dismiss?.rec.case.id ?? null}
        caseLabel={dismiss ? caseNumber(dismiss.rec.case) : ""}
        actingOfficeId={officeId}
        departments={departments}
        suggestFirst={dismiss?.suggest}
        onClose={() => setDismiss(null)}
        onDone={() => {
          setDismiss(null);
          refresh();
        }}
      />
    </>
  );
}

export function ClaimedPanel({ officeId, page, setPage }: { officeId?: string; page: number; setPage: (p: number) => void }) {
  const list = useApi<Page<CaseCard>>("/inbox/claimed", { office_id: officeId, page, size: SIZE });
  return (
    <Async state={list} loadingLabel="Loading claimed cases">
      {(p) =>
        p.items.length === 0 ? (
          <Empty title="No cases claimed yet" center>
            Claim a recommended case, or one from the unclaimed pool, to start tracking it.
          </Empty>
        ) : (
          <>
            <CardList>
              {p.items.map((c) => (
                <TrackingCard key={c.id} c={c} />
              ))}
            </CardList>
            <Pagination page={p.page} size={p.size} total={p.total} onPage={setPage} noun="cases" />
          </>
        )
      }
    </Async>
  );
}

export function UnclaimedPanel({
  officeId,
  canAct,
  onChanged,
  q,
  page,
  setQ,
  setPage,
}: Common & { q: string; page: number; setQ: (q: string) => void; setPage: (p: number) => void }) {
  const list = useApi<Page<CaseCard>>("/inbox/unclaimed", { q: q || undefined, page, size: SIZE });
  const [draft, setDraft] = useState(q);
  const refresh = () => {
    list.reload();
    onChanged();
  };
  const { busyId, claim } = useClaim(officeId, refresh);
  const submit = (e: FormEvent) => {
    e.preventDefault();
    setQ(draft.trim());
  };
  return (
    <>
      <form role="search" onSubmit={submit} style={{ display: "flex", gap: 10, alignItems: "flex-end", flexWrap: "wrap" }}>
        <Field label="Search the unclaimed pool">
          <TextInput type="search" value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="Case number, party name or CNR" style={{ minWidth: 320 }} />
        </Field>
        <Button type="submit" icon="search">
          Search
        </Button>
      </form>
      <Async state={list} loadingLabel="Loading the unclaimed pool">
        {(p) =>
          p.items.length === 0 ? (
            <Empty title={q ? "No unclaimed case matches" : "The unclaimed pool is empty"} center />
          ) : (
            <>
              <CardList>
                {p.items.map((c) => (
                  <TrackingCard
                    key={c.id}
                    c={c}
                    actions={
                      canAct ? (
                        <Button variant="primary" icon="claim" busy={busyId === c.id} onClick={() => claim(c)}>
                          Claim
                        </Button>
                      ) : undefined
                    }
                  />
                ))}
              </CardList>
              <Pagination page={p.page} size={p.size} total={p.total} onPage={setPage} noun="cases" />
            </>
          )
        }
      </Async>
    </>
  );
}

function transferPill(t: Transfer) {
  if (t.status === "requested") return <Pill tone="warning">Awaiting decision</Pill>;
  if (t.status === "accepted") return <Pill tone="success">Accepted</Pill>;
  if (t.status === "declined") return <Pill tone="criticalSoft">Declined</Pill>;
  return <Pill tone="muted">Withdrawn</Pill>;
}

export function TransfersPanel({ officeId, canAct, onChanged }: Common) {
  const list = useApi<Transfer[]>("/inbox/transfers", { office_id: officeId });
  const toast = useToast();
  const [busy, setBusy] = useState<string | null>(null);
  const [decline, setDecline] = useState<Transfer | null>(null);

  const decide = async (t: Transfer, action: "accept" | "decline" | "withdraw", reason?: string): Promise<boolean> => {
    setBusy(t.id);
    try {
      await api.post(`/transfers/${t.id}/${action}`, { office_id: officeId ?? null, reason: reason || null });
      toast.success(
        action === "accept"
          ? `Transfer accepted. ${caseNumber(t.case)} is now held by your department.`
          : action === "decline"
            ? "Transfer declined."
            : "Transfer request withdrawn.",
      );
      list.reload();
      onChanged();
      return true;
    } catch (e) {
      toast.error(e);
      return false;
    } finally {
      setBusy(null);
    }
  };

  return (
    <>
      <Async state={list} loadingLabel="Loading transfers">
        {(items) =>
          items.length === 0 ? (
            <Empty title="No transfer requests" center>
              Requests to hand a case to another department, in either direction, appear here.
            </Empty>
          ) : (
            <CardList>
              {items.map((t) => (
                <TrackingCard
                  key={t.id}
                  c={t.case}
                  extra={
                    <div style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 13 }}>
                      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                        <Pill tone={t.direction === "incoming" ? "info" : "infoSoft"}>{t.direction === "incoming" ? "Incoming" : "Outgoing"}</Pill>
                        {transferPill(t)}
                        <span className="muted">
                          {t.from_office.name} to {t.to_office.name}
                        </span>
                      </div>
                      <span className="muted">
                        Requested {fmtDateTime(t.created_at)}
                        {t.requested_by ? ` by ${t.requested_by}` : ""}
                        {t.reason ? ` · “${t.reason}”` : ""}
                      </span>
                    </div>
                  }
                  actions={
                    canAct && t.status === "requested" ? (
                      t.direction === "incoming" ? (
                        <>
                          <Button variant="primary" busy={busy === t.id} onClick={() => decide(t, "accept")}>
                            Accept
                          </Button>
                          <Button disabled={busy === t.id} onClick={() => setDecline(t)}>
                            Decline
                          </Button>
                        </>
                      ) : (
                        <Button busy={busy === t.id} onClick={() => decide(t, "withdraw")}>
                          Withdraw
                        </Button>
                      )
                    ) : undefined
                  }
                />
              ))}
            </CardList>
          )
        }
      </Async>
      <ReasonDialog
        open={decline !== null}
        title="Decline transfer"
        description={decline ? `${caseNumber(decline.case)} stays with ${decline.from_office.name}.` : undefined}
        submitLabel="Decline"
        danger
        onClose={() => setDecline(null)}
        onConfirm={async (reason) => {
          if (!decline) return false;
          const ok = await decide(decline, "decline", reason);
          if (ok) setDecline(null);
          return ok;
        }}
      />
    </>
  );
}
