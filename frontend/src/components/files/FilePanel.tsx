"use client";

/**
 * The side panel of a Files row (design portal-ui-redesign, decision 26, Work list template): the row's card details
 * and the full remark, with "Open case page" when the caller can open the case. Nothing here acts on the file:
 * sending and recalling stay on the case page, where the card's flags are current (portal-files-alerts, decision 12).
 */
import Link from "next/link";
import type { ReactNode } from "react";

import { buttonClass, CaseLink, KvList, SidePanel, type CaseRefLike } from "@/components/ui";
import { T } from "@/lib/messages";
import { casePath } from "@/lib/refs";

import s from "./files.module.css";

export function FilePanel({
  caseRef,
  visible = true,
  facts,
  remark,
  onClose,
}: {
  caseRef: (CaseRefLike & { petitioner_summary?: string | null; respondent_summary?: string | null }) | null;
  visible?: boolean;
  facts: [ReactNode, ReactNode][];
  remark: string | null | undefined;
  onClose: () => void;
}) {
  const title = caseRef ? caseRef.case_no_text || caseRef.ref_no : T.files.details;
  return (
    <SidePanel
      open={caseRef !== null}
      title={title}
      onClose={onClose}
      footer={
        caseRef && visible ? (
          <Link href={casePath(caseRef.ref_no)} className={buttonClass("primary")} data-variant="primary">
            {T.files.openCase}
          </Link>
        ) : null
      }
    >
      {caseRef ? (
        <div className="stack">
          <KvList items={[[T.files.case, <CaseLink key="c" value={caseRef} visible={visible} />], ...facts]} />
          <section aria-label={T.files.remark}>
            <h3>{T.files.remark}</h3>
            {remark ? <div className={s.full}>{remark}</div> : <p className="muted">{T.files.noRemark}</p>}
          </section>
        </div>
      ) : null}
    </SidePanel>
  );
}
