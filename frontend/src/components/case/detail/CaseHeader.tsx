import type { ReactNode } from "react";
import { fmtDate } from "@/lib/format";
import type { CaseCard, CaseDetail } from "@/lib/types";
import { Pill, StatusPill } from "../../ui/Pill";
import { caseNumber } from "../CaseBits";
import s from "./detail.module.css";
import { CustodyStrip } from "./Workflow";

export function CaseHeader({ c, rail }: { c: CaseCard | CaseDetail; rail?: ReactNode }) {
  const detail = "registration_date" in c ? c : null;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <div className={s.header}>
        <div className={s.headMain}>
          <div className={s.headTop}>
            <StatusPill status={c.status} />
            {c.case_type ? (
              <span className="muted" style={{ fontSize: 14 }}>
                {c.case_type}
              </span>
            ) : null}
            {c.is_provisional ? <Pill tone="warning">Provisional record (no CNR yet)</Pill> : null}
            {!c.in_scope ? <Pill tone="muted">Tracking card only</Pill> : null}
          </div>
          <h1 className={s.caseNo}>{caseNumber(c)}</h1>
          <div className={s.parties}>
            {c.petitioner ?? "Petitioner not yet known"} <span className={s.vs}>vs.</span> {c.respondent ?? "Respondent not yet known"}
          </div>
          <div className={s.headMeta}>
            <span title="Portal reference number: quote it in correspondence">
              Ref <span className="mono">{c.ref_no}</span>
            </span>
            {c.cnr ? (
              <span>
                · CNR <span className="mono">{c.cnr}</span>
              </span>
            ) : null}
            {c.court ? <span>· {c.court}</span> : null}
            {detail?.registration_date ? <span>· Registered {fmtDate(detail.registration_date)}</span> : null}
            {c.filing_no ? (
              <span>
                · Filing <span className="mono">{c.filing_no}</span>
              </span>
            ) : null}
            {c.disposal_date ? <span>· Disposed {fmtDate(c.disposal_date)}</span> : null}
          </div>
        </div>
        {rail ? <div className={`${s.rail} no-print`}>{rail}</div> : null}
      </div>
      <CustodyStrip c={c} />
    </div>
  );
}
