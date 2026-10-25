"use client";

/**
 * The old inbox addresses (design portal-ui-redesign, decision 10.4): client redirects that keep the query string, so
 * a bookmark or an e-mailed link still lands on the same list (also the old Files addresses, design case-workspace-admin,
 * decision 3, and the old Cases list addresses, design case-inbox-merge, decision 12). `/inbox/recommended`, `/inbox/pool` and
 * `/inbox/transfers` go to Case claim; `/inbox/claimed` goes to Department cases when the API says `whole_department`,
 * else to Working on; `/inbox` opens the first tab the login may open (`InboxIndex`).
 */
import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { Loading } from "@/components/ui";
import { useInboxCounts, useMe } from "@/lib/api/hooks";
import { can } from "@/lib/can";
import { queryString, type Params } from "@/lib/params";

function useReplace(target: string | null) {
  const router = useRouter();
  useEffect(() => {
    if (target) router.replace(target);
  }, [router, target]);
}

/** `to` with the old address's query string; a query in `to` itself (`/inbox/working?held=offices`) is kept and wins. */
export function redirectTarget(to: string, params: Params): string {
  const [path, query] = to.split("?", 2);
  const own: Params = Object.fromEntries(new URLSearchParams(query ?? ""));
  return path + queryString({ ...params, ...own });
}

/** A fixed new address with the same query string. */
export function Redirect({ to, params }: { to: string; params: Params }) {
  useReplace(redirectTarget(to, params));
  return <Loading />;
}

/** `/inbox/claimed`: Department cases for a whole-department reader, otherwise Working on. */
export function ClaimedRedirect({ params }: { params: Params }) {
  const me = useMe();
  const counts = useInboxCounts(null, !!me.data);
  const wanted = params.department?.trim().toUpperCase();
  let target: string | null = null;
  if (me.data && (counts.data || counts.error)) {
    const blocks = counts.data?.departments ?? [];
    const whole = wanted
      ? can(me.data, "cases.view_all") || blocks.some((b) => b.office_code === wanted && b.whole_department)
      : can(me.data, "cases.view_all") || blocks.some((b) => b.whole_department);
    target = (whole ? "/inbox/department" : "/inbox/working") + queryString(params);
  } else if (me.error) {
    target = "/inbox/working" + queryString(params);
  }
  useReplace(target);
  return <Loading />;
}
