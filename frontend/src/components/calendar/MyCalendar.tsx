"use client";

/**
 * My calendar (design portal-ui-redesign, decision 8; plan §5.5; API A6): a month grid of the user's own dates from
 * `GET /me/calendar` in three colours — red hearings of my cases, amber my action due dates, blue next dates waiting for
 * my confirmation — with Previous / Next month and Today, the month and the chosen day in the query string
 * (`?month=YYYY-MM&day=YYYY-MM-DD`), legend chips that hide a kind on screen (display only; the API returns all three),
 * and the agenda of the chosen day beside the grid (below it on tablets and phones).
 *
 * Whole-department members (`whole_department` on `/inbox/counts`, A4) and State-wide readers also get the switch
 * "My dates | Department hearings" (`?view=department`), which shows today's hearing calendar of `GET /calendar`
 * unchanged, so no one loses the view they had. Nothing is worked out in the browser beyond the grid's days.
 */
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { useFilters } from "@/components/inbox/common";
import { Button, Card, Chip, ChipGroup, ErrorBanner, Loading, PageHeader, SegmentedSwitch, cx } from "@/components/ui";
import { api, ApiError } from "@/lib/api/client";
import { useInboxCounts, useMe } from "@/lib/api/hooks";
import type { MyCalendarList } from "@/lib/api/types";
import { byDate, gridRange, KINDS, parseDay, type Kind } from "@/lib/calendar";
import { can } from "@/lib/can";
import { formatMonthYear } from "@/lib/format";
import { T, type ErrorTexts } from "@/lib/messages";
import type { Params } from "@/lib/params";
import { showsInbox } from "@/lib/routes";
import { monthOf, parseMonth, shiftMonth, todayIst } from "@/lib/workflow";

import s from "./calendar.module.css";
import { DayAgenda } from "./DayAgenda";
import { DepartmentHearings } from "./DepartmentHearings";
import { MonthGrid } from "./MonthGrid";

/** A bad range answers 422 `bad_range`; the server's own words are shown. */
function rangeErrors(error: unknown): ErrorTexts {
  const message = error instanceof ApiError ? error.message : null;
  return message ? { bad_range: () => message } : {};
}

/** Whether the login gets the Department hearings view: a State-wide reader, or a department the server reads whole. */
export function useDepartmentView(): { ready: boolean; allowed: boolean } {
  const me = useMe();
  const stateWide = can(me.data, "cases.view_all");
  const counts = useInboxCounts(null, !!me.data && !stateWide && showsInbox(me.data));
  if (!me.data) return { ready: false, allowed: false };
  if (stateWide) return { ready: true, allowed: true };
  if (!showsInbox(me.data)) return { ready: true, allowed: false };
  if (counts.isPending) return { ready: false, allowed: false };
  return { ready: true, allowed: (counts.data?.departments ?? []).some((b) => b.whole_department) };
}

function MyDates({ params }: { params: Params }) {
  const setFilters = useFilters(params);
  const today = todayIst();
  const month = parseMonth(params.month) ?? monthOf(today);
  const day = parseDay(params.day) ?? (month === monthOf(today) ? today : null);
  const [hidden, setHidden] = useState<Set<Kind>>(new Set());
  const range = gridRange(month);
  const list = useQuery({
    queryKey: ["calendar", "me", range.from, range.to],
    queryFn: () => api<MyCalendarList>("/me/calendar", { query: { from: range.from, to: range.to } }),
    placeholderData: keepPreviousData,
  });
  const items = list.data?.items ?? [];
  const dayItems = day ? (byDate(items.filter((i) => !hidden.has(i.kind as Kind))).get(day) ?? []) : [];

  function toggle(kind: Kind) {
    setHidden((prev) => {
      const next = new Set(prev);
      if (next.has(kind)) next.delete(kind);
      else next.add(kind);
      return next;
    });
  }

  return (
    <div className={s.wrap}>
      <Card>
        <div className={s.head}>
          <Button variant="ghost" aria-label={T.mycal.previous} onClick={() => setFilters({ month: shiftMonth(month, -1), day: undefined })}>
            <span aria-hidden="true">‹</span>
          </Button>
          <h2 className={s.title} aria-live="polite">
            {formatMonthYear(`${month}-01`)}
          </h2>
          <Button variant="ghost" aria-label={T.mycal.next} onClick={() => setFilters({ month: shiftMonth(month, 1), day: undefined })}>
            <span aria-hidden="true">›</span>
          </Button>
          <Button variant="secondary" onClick={() => setFilters({ month: undefined, day: undefined })}>
            {T.mycal.today}
          </Button>
          <div className={s.legend}>
            <ChipGroup label={T.mycal.legend}>
              {KINDS.map((kind) => (
                <Chip key={kind} on={!hidden.has(kind)} onClick={() => toggle(kind)}>
                  <i className={cx(s.swatch, s[`sw-${kind}`])} aria-hidden="true" />
                  {T.mycal.kinds[kind]}
                </Chip>
              ))}
            </ChipGroup>
          </div>
        </div>
        <ErrorBanner error={list.error} onRetry={() => list.refetch()} messages={rangeErrors(list.error)} />
        {list.isPending ? <Loading lines={6} /> : null}
        {list.data ? (
          <MonthGrid
            month={month}
            items={items}
            today={today}
            selected={day}
            hidden={hidden}
            onSelect={(d) => setFilters({ month: monthOf(d), day: d })}
          />
        ) : null}
      </Card>
      <DayAgenda day={day} items={dayItems} />
    </div>
  );
}

export function MyCalendar({ params }: { params: Params }) {
  const me = useMe();
  const setFilters = useFilters(params);
  const view = useDepartmentView();
  if (me.isPending) return <Loading />;
  const department = params.view === "department" && view.allowed;
  return (
    <div className="stack">
      <PageHeader
        title={T.mycal.title}
        subtitle={T.mycal.subtitle}
        actions={
          view.allowed ? (
            <SegmentedSwitch
              label={T.mycal.views}
              options={[
                { value: "mine", label: T.mycal.mine },
                { value: "department", label: T.mycal.department },
              ]}
              value={department ? "department" : "mine"}
              onChange={(v) =>
                setFilters({ view: v === "department" ? "department" : undefined, month: undefined, day: undefined, department: undefined })
              }
            />
          ) : null
        }
      />
      {params.view === "department" && !view.ready ? <Loading /> : department ? <DepartmentHearings params={params} /> : <MyDates params={params} />}
    </div>
  );
}
