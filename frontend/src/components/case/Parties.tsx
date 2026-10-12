"use client";

/**
 * The Parties tab (design portal-cases, decision 10): every party and advocate, former ones behind "Show former"
 * (`include_former`), counsel codes shown.
 */
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { CheckField, EmptyState, ErrorBanner, Loading, Table } from "@/components/ui";
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
              <Table caption={T.case.parties}>
                <thead>
                  <tr>
                    <th scope="col">{T.case.role}</th>
                    <th scope="col">#</th>
                    <th scope="col">{T.case.name}</th>
                    <th scope="col">{T.case.address}</th>
                  </tr>
                </thead>
                <tbody>
                  {list.data.parties.map((p) => (
                    <tr key={`${p.role}-${p.party_no}-${p.name}`}>
                      <td>{p.role}</td>
                      <td>{p.party_no}</td>
                      <td>
                        {p.name}
                        {!p.is_current ? <span className="muted"> ({T.case.former})</span> : null}
                      </td>
                      <td>{p.address ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            )}
          </section>
          <section aria-label={T.case.advocates}>
            <h2>{T.case.advocates}</h2>
            {list.data.advocates.length === 0 ? (
              <EmptyState>{T.case.none}</EmptyState>
            ) : (
              <Table caption={T.case.advocates}>
                <thead>
                  <tr>
                    <th scope="col">{T.case.side}</th>
                    <th scope="col">{T.case.name}</th>
                    <th scope="col">{T.case.counselCodes}</th>
                  </tr>
                </thead>
                <tbody>
                  {list.data.advocates.map((a, i) => (
                    <tr key={`${a.side}-${a.name_as_listed}-${i}`}>
                      <td>{a.side}</td>
                      <td>
                        {a.name_as_listed}
                        {a.bar_reg_no ? <span className="muted"> · {a.bar_reg_no}</span> : null}
                        {!a.is_current ? <span className="muted"> ({T.case.former})</span> : null}
                      </td>
                      <td className="mono">{a.counsel_code ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            )}
          </section>
        </>
      ) : null}
    </div>
  );
}
