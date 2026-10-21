"use client";

/**
 * The Parties tab (design portal-cases, decision 10): every party and advocate, former ones behind "Show former"
 * (`include_former`), counsel codes shown.
 */
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { CheckField, DataTable, EmptyState, ErrorBanner, Loading } from "@/components/ui";
import { api } from "@/lib/api/client";
import { caseKey } from "@/lib/api/hooks";
import type { Parties as PartiesOut } from "@/lib/api/types";
import { T } from "@/lib/messages";
import { apiCasePath } from "@/lib/refs";

export function Parties({ caseRef }: { caseRef: string }) {
  const [former, setFormer] = useState(false);
  const list = useQuery({
    queryKey: [...caseKey(caseRef), "parties", former],
    queryFn: () =>
      api<PartiesOut>(`${apiCasePath(caseRef)}/parties`, { query: { include_former: former || undefined } }),
  });
  return (
    <div className="stack">
      <CheckField label={T.case.showFormer} checked={former} onChange={(e) => setFormer(e.target.checked)} />
      {list.isPending ? <Loading /> : null}
      <ErrorBanner error={list.error} onRetry={() => list.refetch()} />
      {list.data ? (
        <>
          <section aria-label={T.case.parties}>
            <h2>{T.case.parties}</h2>
            {list.data.parties.length === 0 ? (
              <EmptyState>{T.case.none}</EmptyState>
            ) : (
              <DataTable
                caption={T.case.parties}
                rows={list.data.parties}
                rowKey={(p) => `${p.role}-${p.party_no}-${p.name}`}
                columns={[
                  { key: "role", header: T.case.role, cell: (p) => p.role },
                  { key: "no", header: "#", label: T.case.partyNo, align: "right", cell: (p) => p.party_no },
                  {
                    key: "name",
                    header: T.case.name,
                    primary: true,
                    cell: (p) => (
                      <>
                        {p.name}
                        {!p.is_current ? <span className="muted"> ({T.case.former})</span> : null}
                      </>
                    ),
                  },
                  { key: "address", header: T.case.address, cell: (p) => p.address ?? "—" },
                ]}
              />
            )}
          </section>
          <section aria-label={T.case.advocates}>
            <h2>{T.case.advocates}</h2>
            {list.data.advocates.length === 0 ? (
              <EmptyState>{T.case.none}</EmptyState>
            ) : (
              <DataTable
                caption={T.case.advocates}
                rows={list.data.advocates.map((a, i) => ({ a, i }))}
                rowKey={({ a, i }) => `${a.side}-${a.name_as_listed}-${i}`}
                columns={[
                  { key: "side", header: T.case.side, cell: ({ a }) => a.side },
                  {
                    key: "name",
                    header: T.case.name,
                    primary: true,
                    cell: ({ a }) => (
                      <>
                        {a.name_as_listed}
                        {a.bar_reg_no ? <span className="muted"> · {a.bar_reg_no}</span> : null}
                        {!a.is_current ? <span className="muted"> ({T.case.former})</span> : null}
                      </>
                    ),
                  },
                  { key: "codes", header: T.case.counselCodes, cell: ({ a }) => <span className="mono">{a.counsel_code ?? "—"}</span> },
                ]}
              />
            )}
          </section>
        </>
      ) : null}
    </div>
  );
}
