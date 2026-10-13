"use client";

/**
 * The hearing calendar (design portal-files-alerts, decisions 10 and 11; portal-workflow decision 17; plan §5.5
 * "Calendar of upcoming hearings for the user's cases, with critical (within 48 hours) and this-week highlights").
 * Two views in the query string: "Next 7 days" (the API's default range, the agenda only) and a month
 * (`?month=YYYY-MM`, the grid then the agenda). The badges come from the API's `critical` / `this_week`, never from
 * the browser. A State-wide reader chooses a department first (`?department=CODE`, sent as `office`); until then
 * nothing is requested.
 */
import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { useFilters } from "@/components/inbox/common";
import { Badge, Button, CaseLink, EmptyState, ErrorBanner, Loading, SelectField } from "@/components/ui";
import { api, ApiError } from "@/lib/api/client";
import { useDepartments, useMe } from "@/lib/api/hooks";
import type { CalendarItem, CalendarList } from "@/lib/api/types";
import { can } from "@/lib/can";
import { T, type ErrorTexts } from "@/lib/messages";
import type { Params } from "@/lib/params";
import { monthGrid, monthOf, monthRange, parseMonth, shiftMonth, todayIst } from "@/lib/workflow";

import cs from "@/components/case/case.module.css";

import s from "./alerts.module.css";

const DAY = new Intl.DateTimeFormat("en-IN", { timeZone: "UTC", day: "numeric", month: "long" });
const DAY_FULL = new Intl.DateTimeFormat("en-IN", { timeZone: "UTC", weekday: "long", day: "numeric", month: "long", year: "numeric" });
const MONTH = new Intl.DateTimeFormat("en-IN", { timeZone: "UTC", month: "long", year: "numeric" });

function utc(ymd: string): Date {
  const [y, m, d] = ymd.split("-").map(Number) as [number, number, number];
  return new Date(Date.UTC(y, m - 1, d));
}

export function dayLabel(ymd: string): string {
  return DAY.format(utc(ymd));
}

export function monthLabel(month: string): string {
  return MONTH.format(utc(`${month}-01`));
}

/** `bad_range` means the load console's range elsewhere; here the server's own words are shown (decision 16). */
function calendarErrors(error: unknown): ErrorTexts {
  const message = error instanceof ApiError ? error.message : null;
  return message ? { bad_range: () => message } : {};
}

function sourceLabel(source: string): string {
  return T.cal.sources[source] ?? source;
}

/** Items by date, ascending (the API's order kept within a day). */
export function groupByDate(items: CalendarItem[]): [string, CalendarItem[]][] {
  const map = new Map<string, CalendarItem[]>();
  for (const item of items) {
    const list = map.get(item.date) ?? [];
    list.push(item);
    map.set(item.date, list);
  }
  return [...map.entries()].sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
}

export function MonthGrid({ month, items, today }: { month: string; items: CalendarItem[]; today: string }) {
  const byDate = new Map(groupByDate(items));
  return (
    <table className={s.grid}>
      <caption>{monthLabel(month)}</caption>
      <thead>
        <tr>
          {T.cal.weekdays.map((day, i) => (
            <th key={day} scope="col">
              <abbr title={day}>{T.cal.weekdaysShort[i]}</abbr>
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {monthGrid(month).map((week, w) => (
          <tr key={w}>
            {week.map((ymd, d) => {
              if (!ymd) return <td key={d} className={s.outside} />;
              const dayItems = byDate.get(ymd) ?? [];
              const critical = dayItems.filter((i) => i.critical).length;
              const isToday = ymd === today;
              const label = T.cal.dayName(dayLabel(ymd), dayItems.length, critical);
              return (
                <td key={d} className={isToday ? s.today : undefined} aria-current={isToday ? "date" : undefined}>
                  <div className={s.dayNo}>
                    {Number(ymd.slice(8))}
                    {isToday ? <span className="visually-hidden"> {T.cal.today}</span> : null}
                  </div>
                  {dayItems.length > 0 ? (
                    <a href={`#d-${ymd}`} aria-label={label} className={s.dayLink}>
                      <span aria-hidden="true">{T.cal.hearings(dayItems.length)}</span>
                      {critical > 0 ? (
                        <span aria-hidden="true" className={s.critical}>
                          {T.cal.critical}
                        </span>
                      ) : null}
                    </a>
                  ) : null}
                </td>
              );
            })}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function Agenda({ items }: { items: CalendarItem[] }) {
  if (items.length === 0) return <EmptyState>{T.cal.empty}</EmptyState>;
  return (
    <section aria-label={T.cal.agenda} className="stack">
      <h2>{T.cal.agenda}</h2>
      {groupByDate(items).map(([date, dayItems]) => (
        <section key={date} aria-labelledby={`d-${date}`}>
          <h3 id={`d-${date}`} tabIndex={-1}>
            {DAY_FULL.format(utc(date))}
          </h3>
          <ul className="stack" style={{ listStyle: "none", padding: 0 }}>
            {dayItems.map((item, i) => (
              <li key={`${item.case.id}-${item.source}-${i}`} className={cs.note}>
                <div className={cs.noteHead}>
                  <CaseLink value={item.case} />
                  {item.critical ? <Badge tone="danger">{T.cal.critical}</Badge> : null}
                  {item.this_week ? <Badge>{T.cal.thisWeek}</Badge> : null}
                </div>
                <div>
                  {T.cal.court}: {item.court_no ?? "—"} · {T.cal.item}: {item.item_no ?? "—"} · {T.cal.purpose}:{" "}
                  {item.purpose ?? "—"} · {T.cal.source}: {sourceLabel(item.source)}
                </div>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </section>
  );
}

export function Calendar({ params }: { params: Params }) {
  const me = useMe();
  const setFilters = useFilters(params);
  const stateWide = can(me.data, "cases.view_all");
  const departments = useDepartments(stateWide);
  const month = parseMonth(params.month);
  const department = stateWide ? params.department?.trim().toUpperCase() || null : null;
  const range = month ? monthRange(month) : null;
  const ready = !!me.data && (!stateWide || !!department);
  const list = useQuery({
    queryKey: ["alerts", "calendar", range, department],
    queryFn: () =>
      api<CalendarList>("/calendar", {
        query: { from: range?.from, to: range?.to, office: department ?? undefined },
      }),
    enabled: ready,
    placeholderData: keepPreviousData,
  });
  const today = todayIst();
  if (me.isPending) return <Loading />;
  return (
    <div className="stack">
      <div className="row" role="group" aria-label={T.cal.views}>
        <Button variant={month ? "secondary" : "primary"} aria-pressed={!month} onClick={() => setFilters({ month: undefined })}>
          {T.cal.next7}
        </Button>
        <Button
          variant={month === monthOf(today) ? "primary" : "secondary"}
          aria-pressed={month === monthOf(today)}
          onClick={() => setFilters({ month: monthOf(today) })}
        >
          {T.cal.thisMonth}
        </Button>
        {month ? (
          <>
            <Button variant="secondary" onClick={() => setFilters({ month: shiftMonth(month, -1) })}>
              {T.cal.previousMonth}
            </Button>
            <Button variant="secondary" onClick={() => setFilters({ month: shiftMonth(month, 1) })}>
              {T.cal.nextMonth}
            </Button>
          </>
        ) : null}
      </div>
      {stateWide ? (
        <SelectField
          label={T.cal.department}
          placeholder={T.cal.pickDepartment}
          options={(departments.data?.departments ?? []).map((d) => ({ value: d.code, label: `${d.code} — ${d.name}` }))}
          value={department ?? ""}
          onChange={(e) => setFilters({ department: e.target.value || undefined })}
        />
      ) : null}
      {stateWide && !department ? (
        <EmptyState>{T.cal.chooseDepartment}</EmptyState>
      ) : (
        <>
          <ErrorBanner error={list.error} onRetry={() => list.refetch()} messages={calendarErrors(list.error)} />
          {list.isPending ? <Loading /> : null}
          {list.data ? (
            <>
              {month ? <MonthGrid month={month} items={list.data.items} today={today} /> : null}
              <Agenda items={list.data.items} />
            </>
          ) : null}
        </>
      )}
    </div>
  );
}
