"use client";

import { apiUrl } from "@/lib/api";
import { fmtDate, fmtDateTime, hearingBand, humanize } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { CaseDetail, Hearing, Me } from "@/lib/types";
import { Card, CardHead, KV } from "../../ui/Layout";
import { HearingPill, Pill } from "../../ui/Pill";
import { Empty } from "../../ui/States";
import s from "./detail.module.css";
import { NextDates } from "./NextDates";
import { Timeline } from "./Timeline";
import { CustodyTrail, StageCard } from "./Workflow";

function PartyColumn({ title, c, role }: { title: string; c: CaseDetail; role: "petitioner" | "respondent" }) {
  const parties = c.parties.filter((p) => p.role === role).sort((a, b) => a.party_no - b.party_no);
  const advocates = c.advocates.filter((a) => a.side === role);
  const summary = role === "petitioner" ? c.petitioner : c.respondent;
  const advText = role === "petitioner" ? c.pet_advocate : c.res_advocate;
  return (
    <div className={s.partyCol}>
      <div className={s.small}>{title}</div>
      {parties.length ? (
        parties.map((p) => (
          <div key={`${p.role}-${p.party_no}`}>
            <div className={s.partyName}>
              {parties.length > 1 ? `${p.party_no}. ` : ""}
              {p.name}
            </div>
            {p.address ? <div className={s.partyAddr}>{p.address}</div> : null}
          </div>
        ))
      ) : (
        <div className={s.partyName}>{summary ?? "Not recorded"}</div>
      )}
      <div className={s.small}>
        {advocates.length
          ? advocates.map((a) => (
              <div key={`${a.side}-${a.name}`}>
                {a.counsel_code ? <span className="mono">{a.counsel_code} · </span> : null}
                Adv. {a.name}
              </div>
            ))
          : advText
            ? `Adv. ${advText}`
            : "Advocate not recorded"}
      </div>
    </div>
  );
}

export function OverviewTab({ c, me, onChanged, onOpenTab }: { c: CaseDetail; me: Me; onChanged: () => void; onOpenTab: (id: string) => void }) {
  const hearings = useApi<Hearing[]>(`/cases/${c.id}/hearings`);
  const band = hearingBand(c.next_hearing_date);
  const primary = c.ownership.find((o) => o.role === "primary" && o.status === "active");
  const watchers = c.ownership.filter((o) => o.role === "watcher" && o.status === "active");
  const recent = [...(hearings.data ?? [])].sort((a, b) => b.business_date.localeCompare(a.business_date)).slice(0, 4);
  const review = c.next_dates.filter((n) => n.needs_review && (n.review_status === "pending" || n.review_status === "none"));

  return (
    <div className={s.columns}>
      <div className={s.main}>
        <StageCard c={c} canSet={!me.read_only} onChanged={onChanged} />

        <Card labelledBy="ov-next">
          <CardHead id="ov-next" title="Next hearing" caption />
          {c.next_hearing_date ? (
            <>
              <div className={s.bigDateRow}>
                <div className={`${s.bigDate} ${band === "critical" ? s.bigDateCritical : ""}`}>{fmtDate(c.next_hearing_date)}</div>
                <HearingPill date={c.next_hearing_date} />
              </div>
              <KV
                items={[
                  { label: "Court", value: c.court ?? "-" },
                  { label: "Purpose", value: c.next_purpose ?? "-" },
                  { label: "Coram", value: c.coram ?? "-" },
                ]}
              />
            </>
          ) : (
            <Empty title={c.status === "disposed" ? `Disposed${c.disposal_date ? ` on ${fmtDate(c.disposal_date)}` : ""}` : "No next date known yet"} />
          )}
          {review.length ? (
            <div>
              <Pill tone="warning">{review.length === 1 ? "A next date needs review" : `${review.length} next dates need review`}</Pill>
            </div>
          ) : null}
        </Card>

        <Card labelledBy="ov-parties">
          <CardHead id="ov-parties" title="Parties and advocates" caption />
          <div className={s.partyGrid}>
            <PartyColumn title="Petitioner" c={c} role="petitioner" />
            <PartyColumn title="Respondents" c={c} role="respondent" />
          </div>
        </Card>

        <Card labelledBy="ov-reg">
          <CardHead id="ov-reg" title="Registration details" caption />
          <KV
            items={[
              { label: "Case type", value: c.case_type ?? "-" },
              { label: "Filing number", value: c.filing_no ?? "-", mono: true },
              { label: "Filed", value: fmtDate(c.filing_date) },
              { label: "Registered", value: fmtDate(c.registration_date) },
              { label: "Category", value: c.category ?? "-" },
              { label: "Judicial branch", value: c.judicial_branch ?? "-" },
              { label: "Last hearing", value: fmtDate(c.last_hearing_date) },
              { label: "Disposal", value: c.disposal_date ? `${fmtDate(c.disposal_date)}${c.disposal_nature ? ` (${c.disposal_nature})` : ""}` : "-" },
              { label: "Court record refreshed", value: fmtDateTime(c.last_full_refresh_at) },
              { label: "Status checked", value: fmtDateTime(c.last_status_refresh_at) },
              { label: "First seen through", value: humanize(c.first_seen_source) },
            ]}
          />
          {c.acts.length ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              <div className={s.small}>Acts</div>
              {c.acts.map((a, i) => (
                <div key={`${a.act_name}-${i}`} style={{ fontSize: 14 }}>
                  {a.act_name}
                  {a.section ? `, section ${a.section}` : ""}
                </div>
              ))}
            </div>
          ) : null}
        </Card>

        <Card labelledBy="ov-dates">
          <CardHead id="ov-dates" title="Next dates" caption />
          {c.next_dates.length === 0 ? (
            <Empty title="No next dates recorded" />
          ) : (
            <NextDates rows={c.next_dates} canReview={!me.read_only} onChanged={onChanged} />
          )}
        </Card>

        <Card labelledBy="ov-proc">
          <CardHead
            id="ov-proc"
            title="Proceedings"
            caption
            actions={
              <button type="button" onClick={() => onOpenTab("hearings")} style={{ background: "none", border: "none", color: "var(--accent)", fontWeight: 600, cursor: "pointer", minHeight: 36 }}>
                All hearings
              </button>
            }
          />
          {hearings.data === undefined ? (
            <span className="muted">Loading…</span>
          ) : recent.length === 0 ? (
            <Empty title="No proceedings recorded yet" />
          ) : (
            <Timeline
              entries={recent.map((h, i) => ({
                key: `${h.business_date}-${i}`,
                date: h.business_date,
                dateOnly: true,
                title: [h.purpose || "Hearing", h.bench_text].filter(Boolean).join(" · "),
                text: [h.business_text, h.next_date ? `Next date ${fmtDate(h.next_date)}` : null].filter(Boolean).join(" · ") || undefined,
              }))}
            />
          )}
        </Card>
      </div>

      <div className={s.side}>
        <CustodyTrail caseId={c.id} />

        <Card labelledBy="ov-order">
          <CardHead id="ov-order" title="Latest order" caption />
          {c.latest_order ? (
            <>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                <div style={{ fontSize: 15, fontWeight: 600 }}>Order dated {fmtDate(c.latest_order.order_date)}</div>
                {c.latest_order.document_id ? (
                  <a href={apiUrl(`/documents/${c.latest_order.document_id}/download`)} target="_blank" rel="noopener" style={{ fontSize: 13, fontWeight: 600 }}>
                    View order<span className="sr-only"> (opens in a new tab)</span>
                  </a>
                ) : (
                  <Pill tone="muted">Copy not yet downloaded</Pill>
                )}
              </div>
              <div className={s.small}>
                Order no. <span className="mono">{c.latest_order.order_no}</span> · {humanize(c.latest_order.kind)}
              </div>
              {c.next_dates
                .filter((n) => n.order_id === c.latest_order?.id)
                .slice(0, 1)
                .map((n) => (
                  <div key={n.id} style={{ display: "flex", flexDirection: "column", gap: 6, padding: "12px 14px", borderRadius: 8, border: "1px solid var(--border)" }}>
                    <div className={s.small}>Next date read from the order</div>
                    <div style={{ fontSize: 14 }}>
                      Date: <strong>{fmtDate(n.next_date)}</strong>
                    </div>
                    {n.note ? <div style={{ fontSize: 14 }}>{n.note}</div> : null}
                  </div>
                ))}
            </>
          ) : (
            <Empty title="No order collected yet" />
          )}
        </Card>

        <Card labelledBy="ov-own">
          <CardHead id="ov-own" title="Ownership" caption />
          {primary ? (
            <KV
              items={[
                { label: "Primary owner", value: primary.office.name },
                ...(primary.unit || primary.officer
                  ? [
                      {
                        label: "Allotted to",
                        value: [primary.unit?.name, (primary.officer as { name?: string } | null)?.name].filter(Boolean).join(" · "),
                      },
                    ]
                  : []),
                { label: "Watching", value: watchers.length ? watchers.map((w) => w.office.name).join(", ") : "None" },
                { label: "Claimed", value: `${fmtDate(primary.claimed_at)}${primary.claimed_by ? ` by ${primary.claimed_by}` : ""}` },
              ]}
            />
          ) : (
            <p className={s.small}>No department has claimed this case. It is in the unclaimed pool.</p>
          )}
        </Card>
      </div>
    </div>
  );
}
