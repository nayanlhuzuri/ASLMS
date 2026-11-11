"use client";

/**
 * Rows of `/cases`, `/cases/search` and the court search (design portal-cases, decisions 2 and 9): a visible case
 * links to its page; any other shows the court-public summary, the owning department and "in the unclaimed pool",
 * with Claim when `claimable`. Claim opens the dialog without departments: it reads `GET /cases/{ref}/ownership` and
 * offers its `claim_departments` (design portal-cases-followups, decision 7; nothing is computed in the portal).
 * On the Work list template (design portal-ui-redesign, decision 26): a `DataTable` (cards on phones) whose row opens
 * the case's facts in a side panel, with "Open case page" when the caller can open it. The next hearing is the kit's
 * `HearingDate`, on its own line under the last listing and in the panel's Next Hearing row (design
 * next-hearing-highlight, decision 11).
 * Design portal-screen-fixes-oversight, decision 2: the case number leads the case cell (with the CNR muted after it),
 * then the "Court-public Summary Only" mark for a case the caller cannot open, the parties, the last listing and the
 * next hearing, in the order of the inbox's case cell; the number stays a link so a case the caller cannot open shows as
 * text. Status is one badge with at most one muted line (the owner's name or "In the Unclaimed Pool"); the fetch state
 * stays in the side panel. Decision 1: the table's caption is its accessible name only (the section's heading names
 * the list).
 */
import Link from "next/link";
import { useState, type ReactNode } from "react";

import { ClaimDialog } from "@/components/inbox/dialogs";
import { ListingLine, PartiesLine } from "@/components/inbox/common";
import { Chevron } from "@/components/inbox/rows";
import { Badge, Button, buttonClass, CaseLink, type Column, DataTable, HearingDate, KvList, OfficeName, SidePanel } from "@/components/ui";
import type { CaseSearchItem } from "@/lib/api/types";
import { statusTone } from "@/lib/cases";
import { T } from "@/lib/messages";
import { casePath } from "@/lib/refs";
import { labelFor } from "@/lib/displayLabels";

import s from "./search.module.css";

/** Decision 2: the status badge, then one muted line: the owner's name, "In the Unclaimed Pool", or nothing. */
function StatusCell({ it }: { it: CaseSearchItem }) {
  return (
    <div className={s.statusCell}>
      <span>
        <Badge tone={statusTone(it.case.status)}>{labelFor(T.inbox.statuses, it.case.status)}</Badge>
      </span>
      {it.owner_office_code ? (
        <span className="muted" data-status-line="">
          {T.search.ownedBy} <OfficeName code={it.owner_office_code} />
        </span>
      ) : it.in_pool ? (
        <span className="muted" data-status-line="">
          {T.search.inPool}
        </span>
      ) : null}
    </div>
  );
}

/** The "Court-public Summary Only" mark of a case the caller cannot open (decision 2). */
function NotVisibleMark({ it }: { it: CaseSearchItem }) {
  if (it.visible) return null;
  return (
    <span className={s.marks} data-marks="">
      <Badge>{T.search.notVisible}</Badge>
    </span>
  );
}

function CaseCell({ it }: { it: CaseSearchItem }) {
  return (
    <div className={s.caseCell}>
      <span>
        <CaseLink value={it.case} visible={it.visible} />
        {it.case.cnr && it.case.case_no_text ? <span className="mono muted"> · {it.case.cnr}</span> : null}
      </span>
      <NotVisibleMark it={it} />
      <PartiesLine c={it.case} />
      <ListingLine c={it.case} />
      {/* design next-hearing-highlight, decision 11: the next hearing on its own line under the listing */}
      <div>
        <HearingDate next={it.case.next_hearing} status={it.case.status} />
      </div>
    </div>
  );
}

/** The side panel's Status fact: the same two pieces, then the visibility mark and the fetch state (decision 2). */
function PanelStatus({ it }: { it: CaseSearchItem }) {
  return (
    <div className={s.statusCell}>
      <StatusCell it={it} />
      <NotVisibleMark it={it} />
      {it.dossier_status !== "fetched" ? <span className="muted">{T.search.notFetched}</span> : null}
    </div>
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
    { key: "status", header: T.inbox.status, width: "calc(2 * var(--lead-w))", cell: (it) => <StatusCell it={it} /> },
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
                [T.inbox.status, <PanelStatus key="s" it={open} />],
                [T.search.nextHearing, <HearingDate key="n" next={open.case.next_hearing} status={open.case.status} />],
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
