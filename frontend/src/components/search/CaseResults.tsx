"use client";

/**
 * Rows of `/cases`, `/cases/search` and the court search (design portal-cases, decisions 2 and 9): a visible case
 * links to its page; any other shows the court-public summary, the owning department and "in the unclaimed pool",
 * with Claim when `claimable`. Claim opens the dialog without departments: it reads `GET /cases/{ref}/ownership` and
 * offers its `claim_departments` (design portal-cases-followups, decision 7; nothing is computed in the portal).
 * On the Work list template (design portal-ui-redesign, decision 26): a `DataTable` (cards on phones) whose row opens
 * the case's facts in a side panel, with "Open case page" when the caller can open it.
 */
import Link from "next/link";
import { useState, type ReactNode } from "react";

import { ClaimDialog } from "@/components/inbox/dialogs";
import { ListingLine, PartiesLine } from "@/components/inbox/common";
import { Chevron, NextHearingCell } from "@/components/inbox/rows";
import { Button, buttonClass, CaseLink, DataTable, KvList, SidePanel, type Column } from "@/components/ui";
import type { CaseSearchItem } from "@/lib/api/types";
import { T } from "@/lib/messages";
import { casePath } from "@/lib/refs";

function StatusCell({ it }: { it: CaseSearchItem }) {
  return (
    <>
      <div>{T.inbox.statuses[it.case.status] ?? it.case.status}</div>
      {it.owner_office_code ? <div className="muted">{T.search.owner(it.owner_office_code)}</div> : null}
      {it.in_pool ? <div className="muted">{T.search.inPool}</div> : null}
      {!it.visible ? <div className="muted">{T.search.notVisible}</div> : null}
      {it.dossier_status !== "fetched" ? <div className="muted">{T.search.notFetched}</div> : null}
    </>
  );
}

function CaseCell({ it }: { it: CaseSearchItem }) {
  return (
    <>
      <PartiesLine c={it.case} />
      <CaseLink value={it.case} visible={it.visible} />
      {it.case.cnr && it.case.case_no_text ? <span className="mono muted"> · {it.case.cnr}</span> : null}
      <ListingLine c={it.case} />
    </>
  );
}

export function CaseResults({
  items,
  caption,
  extra,
}: {
  items: CaseSearchItem[];
  caption: string;
  extra?: (item: CaseSearchItem) => ReactNode;
}) {
  const [claiming, setClaiming] = useState<string | null>(null);
  const [openId, setOpenId] = useState<string | null>(null);
  // the panel follows the row's latest facts (a court result may be replaced by "Fetch details")
  const open = items.find((i) => i.case.id === openId) ?? null;
  const columns: Column<CaseSearchItem>[] = [
    { key: "case", header: T.inbox.case, primary: true, cell: (it) => <CaseCell it={it} /> },
    { key: "status", header: T.inbox.status, cell: (it) => <StatusCell it={it} /> },
    {
      key: "actions",
      header: T.inbox.actions,
      cell: (it) =>
        it.claimable || extra ? (
          <div className="row">
            {it.claimable ? (
              <Button variant="secondary" onClick={() => setClaiming(it.case.ref_no)}>
                {T.own.claim}
              </Button>
            ) : null}
            {extra ? extra(it) : null}
          </div>
        ) : null,
    },
    { key: "open", header: <span className="visually-hidden">{T.search.details}</span>, hideOnPhone: true, width: "var(--s6)", cell: () => <Chevron /> },
  ];
  return (
    <>
      <DataTable
        caption={caption}
        columns={columns}
        rows={items}
        rowKey={(it) => it.case.id}
        onRowClick={(it) => setOpenId(it.case.id)}
        rowLabel={(it) => T.search.openResult(it.case.case_no_text || it.case.ref_no)}
      />
      <SidePanel
        open={open !== null}
        title={open ? open.case.case_no_text || open.case.ref_no : T.search.details}
        onClose={() => setOpenId(null)}
        footer={
          open && (open.claimable || open.visible) ? (
            <>
              {open.claimable ? (
                <Button
                  variant="secondary"
                  onClick={() => {
                    setOpenId(null);
                    setClaiming(open.case.ref_no);
                  }}
                >
                  {T.own.claim}
                </Button>
              ) : null}
              {open.visible ? (
                <Link href={casePath(open.case.ref_no)} className={buttonClass("primary")} data-variant="primary">
                  {T.search.openCase}
                </Link>
              ) : null}
            </>
          ) : null
        }
      >
        {open ? (
          <div className="stack">
            <KvList
              items={[
                [T.inbox.case, <CaseLink key="c" value={open.case} visible={open.visible} />],
                [T.search.cnrLabel, open.case.cnr ? <span className="mono">{open.case.cnr}</span> : null],
                [T.causelist.parties, <PartiesLine key="p" c={open.case} />],
                [T.inbox.status, <StatusCell key="s" it={open} />],
                [T.search.nextHearing, <NextHearingCell key="n" date={open.case.next_hearing_date} />],
                [T.search.listing, <ListingLine key="l" c={open.case} />],
              ]}
            />
          </div>
        ) : null}
      </SidePanel>
      {claiming ? <ClaimDialog open caseRef={claiming} onClose={() => setClaiming(null)} /> : null}
    </>
  );
}
