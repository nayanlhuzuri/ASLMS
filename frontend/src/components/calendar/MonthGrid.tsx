"use client";

/**
 * My calendar's month grid (design portal-ui-redesign, decision 8): a `<table>` with a caption and weekday headers,
 * Monday first, the days of the neighbouring months dimmed, weekends muted and today circled (IST). A day shows up to
 * two events, coloured by kind (red hearing, amber action due, blue next date to confirm), and "+n more"; on phones
 * the events become dots. Each day is a button whose accessible name says what it holds ("22 October: 1 hearing, 1
 * action due"), so colour is never the only signal; pressing it fills the agenda. Hidden kinds (the legend) are left
 * out of the cells and the names.
 */
import { cx } from "@/components/ui";
import type { MyCalendarItem } from "@/lib/api/types";
import { byDate, dayName, gridWeeks, isWeekend, type Kind } from "@/lib/calendar";
import { formatDayLong, formatMonthYear } from "@/lib/format";
import { T } from "@/lib/messages";

import s from "./calendar.module.css";

const SHOWN_PER_DAY = 2;

export function MonthGrid({
  month,
  items,
  today,
  selected,
  hidden,
  onSelect,
}: {
  month: string;
  items: MyCalendarItem[];
  today: string;
  selected: string | null;
  hidden: ReadonlySet<Kind>;
  onSelect: (day: string) => void;
}) {
  const days = byDate(items.filter((i) => !hidden.has(i.kind as Kind)));
  return (
    <table className={s.grid}>
      <caption className="visually-hidden">{formatMonthYear(`${month}-01`)}</caption>
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
        {gridWeeks(month).map((week) => (
          <tr key={week[0]}>
            {week.map((ymd) => {
              const dayItems = days.get(ymd) ?? [];
              const isToday = ymd === today;
              const outside = ymd.slice(0, 7) !== month;
              const more = dayItems.length - SHOWN_PER_DAY;
              return (
                <td
                  key={ymd}
                  className={cx(outside && s.outside, isWeekend(ymd) && s.weekend, ymd === selected && s.selected)}
                  aria-current={isToday ? "date" : undefined}
                >
                  <button
                    type="button"
                    className={s.day}
                    aria-pressed={ymd === selected}
                    aria-label={`${dayName(formatDayLong(ymd), dayItems)}${isToday ? ` (${T.cal.today})` : ""}`}
                    onClick={() => onSelect(ymd)}
                  >
                    <span className={cx(s.dayNo, isToday && s.today)} aria-hidden="true">
                      {Number(ymd.slice(8))}
                    </span>
                    {dayItems.slice(0, SHOWN_PER_DAY).map((item, i) => (
                      <span key={`${item.kind}-${item.case.id}-${i}`} className={cx(s.ev, s[`ev-${item.kind}`])} aria-hidden="true" data-kind={item.kind}>
                        {item.case.case_no_text ?? item.case.ref_no}
                      </span>
                    ))}
                    {more > 0 ? (
                      <span className={s.moreEv} aria-hidden="true">
                        {T.mycal.moreEvents(more)}
                      </span>
                    ) : null}
                  </button>
                </td>
              );
            })}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
