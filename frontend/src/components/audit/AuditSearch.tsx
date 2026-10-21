"use client";

/**
 * The Audit log search (design portal-audit-health, decisions 3-5 and 8; plan §5.13): the filters come from the URL,
 * named as the API names them, and the first page is requested at once (with none, the newest 50 entries). "Search"
 * writes the filters to the URL, so a link, a bookmark or Back restores the same search; "Clear" goes to `/audit`;
 * "Refresh" re-reads from the newest entry; "More" follows the API's `next_cursor`. A 403 shows who reads the log
 * and nothing else. Searching writes nothing; the screen shows the rows as the API returns them. On the Work list
 * template (design portal-ui-redesign, decision 26): the filters in a card on top, the rows below as a table that
 * becomes cards on phones.
 */
import { useInfiniteQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";

import { Button, Card, EmptyState, ErrorBanner, Loading, PageHeader } from "@/components/ui";
import { api, ApiError } from "@/lib/api/client";
import { useAuditActions } from "@/lib/api/hooks";
import type { AuditPage } from "@/lib/api/types";
import { AUDIT_PAGE, auditParams, checkFilters, fieldOfError, type ErrorField } from "@/lib/audit";
import { formatNumber, istDay } from "@/lib/format";
import { T } from "@/lib/messages";
import { queryString, type Params } from "@/lib/params";

import { AuditFilters } from "./AuditFilters";
import { AuditTable } from "./AuditTable";

/** The API's refusals that a field shows, by code (else the banner shows the API's message). */
function fieldMessage(error: ApiError): string {
  switch (error.code) {
    case "unknown_user":
      return T.audit.unknownUser;
    case "not_found":
      return T.audit.noCase;
    case "bad_office":
      return T.audit.badOffice;
    case "bad_actor":
      return T.audit.actorProblem;
    default:
      return error.message;
  }
}

/** The screen's own text for a code that means something else on the Reports screen. */
const ERROR_TEXTS = { search_timeout: () => T.audit.timeout };

function noRetry(count: number, error: unknown): boolean {
  return !(error instanceof ApiError && error.status >= 400) && count < 2;
}

export function AuditSearch({ params }: { params: Params }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const today = istDay();
  const apiParams = auditParams(params);
  const urlProblems = checkFilters(apiParams, today);
  const key = ["audit", apiParams] as const;
  const search = useInfiniteQuery({
    queryKey: key,
    queryFn: ({ pageParam }) =>
      api<AuditPage>("/audit", { query: { ...apiParams, limit: AUDIT_PAGE, cursor: pageParam } }),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    staleTime: 30_000,
    retry: noRetry,
    enabled: !urlProblems,
  });
  const forbidden = search.error instanceof ApiError && search.error.status === 403;
  // the action list once the search has answered (a 403 requests nothing more)
  const actions = useAuditActions(!forbidden && (!!urlProblems || search.status !== "pending"));

  if (forbidden || (actions.error instanceof ApiError && actions.error.status === 403)) {
    return (
      <div className="stack">
        <PageHeader title={T.audit.title} />
        <EmptyState>{T.audit.readersOnly}</EmptyState>
      </div>
    );
  }

  const error = search.error;
  const fields: ErrorField[] = error instanceof ApiError ? fieldOfError(error.code, apiParams) : [];
  const apiErrors: Partial<Record<ErrorField, string>> = {};
  if (error instanceof ApiError) for (const f of fields) apiErrors[f] = fieldMessage(error);
  const items = search.data?.pages.flatMap((p) => p.items) ?? [];

  return (
    <div className="stack">
      <PageHeader title={T.audit.title} subtitle={T.audit.subtitle} />
      <Card>
        <AuditFilters
        key={queryString(apiParams)}
        params={apiParams}
        today={today}
        actions={actions.data?.actions ?? []}
        apiErrors={apiErrors}
        initialProblems={urlProblems}
        busy={search.isFetching}
        onSearch={(next) => router.push("/audit" + queryString(next))}
        onClear={() => router.push("/audit")}
        onRefresh={() => void queryClient.resetQueries({ queryKey: key, exact: true })}
        />
      </Card>
      {error && fields.length === 0 ? <ErrorBanner error={error} messages={ERROR_TEXTS} onRetry={() => void search.refetch()} /> : null}
      {!urlProblems && search.isPending && !error ? <Loading lines={6} /> : null}
      {search.data && fields.length === 0 ? (
        items.length === 0 ? (
          <EmptyState title={T.audit.emptyTitle}>{T.audit.empty}</EmptyState>
        ) : (
          <>
            <p className="muted" aria-live="polite">
              {T.audit.shown(formatNumber(items.length), !!search.hasNextPage)}
            </p>
            <AuditTable rows={items} params={apiParams} />
          </>
        )
      ) : null}
      {search.hasNextPage && fields.length === 0 ? (
        <div>
          <Button variant="secondary" busy={search.isFetchingNextPage} onClick={() => void search.fetchNextPage()}>
            {T.audit.moreRows}
          </Button>
        </div>
      ) : null}
    </div>
  );
}
