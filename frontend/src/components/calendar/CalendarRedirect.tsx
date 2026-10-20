"use client";

/**
 * `/alerts/calendar` (design portal-ui-redesign, decision 8): a client redirect, keeping the query string, to
 * `/calendar?view=department` for whole-department members and State-wide readers (the Department hearings view, the
 * calendar they had here), and to `/calendar` for everyone else.
 */
import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { Loading } from "@/components/ui";
import { queryString, type Params } from "@/lib/params";

import { useDepartmentView } from "./MyCalendar";

export function CalendarRedirect({ params }: { params: Params }) {
  const router = useRouter();
  const view = useDepartmentView();
  const target = view.ready
    ? "/calendar" + queryString(view.allowed ? { ...params, view: "department" } : { ...params, view: undefined })
    : null;
  useEffect(() => {
    if (target) router.replace(target);
  }, [router, target]);
  return <Loading />;
}
