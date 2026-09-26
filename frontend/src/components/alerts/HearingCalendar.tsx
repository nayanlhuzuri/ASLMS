"use client";

import Link from "next/link";
import { useState } from "react";
import { fmtDate, hearingBand, isoDate, monthTitle, parties, todayIST } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { CalendarItem } from "@/lib/types";
import { caseNumber } from "../case/CaseBits";
import { Button } from "../ui/Button";
import { Card } from "../ui/Layout";
import { Async } from "../ui/States";
import s from "./calendar.module.css";

const DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const PER_CELL = 3;

function eventClass(it: CalendarItem): string {
  if (it.severity === "critical" || hearingBand(it.date) === "critical") return `${s.event} ${s.eventCritical}`;
  if (it.severity === "high" || hearingBand(it.date) === "week") return `${s.event} ${s.eventHigh}`;
  return s.event;
}

/** Month grid of hearings; hearings within 48 hours and this week are highlighted. Phones get an agenda list. */
export function HearingCalendar() {
  const today = todayIST();
  const [y0, m0] = [Number(today.slice(0, 4)), Number(today.slice(5, 7)) - 1];
  const [ym, setYm] = useState({ y: y0, m: m0 });
  const first = new Date(Date.UTC(ym.y, ym.m, 1));
  const lead = (first.getUTCDay() + 6) % 7; // Monday first
  const daysInMonth = new Date(Date.UTC(ym.y, ym.m + 1, 0)).getUTCDate();
  const cells = Math.ceil((lead + daysInMonth) / 7) * 7;
  const from = isoDate(ym.y, ym.m, 1 - lead);
  const to = isoDate(ym.y, ym.m, cells - lead);
  const state = useApi<CalendarItem[]>("/calendar", { from, to });

  const shift = (n: number) => setYm(({ y, m }) => ({ y: m + n < 0 ? y - 1 : m + n > 11 ? y + 1 : y, m: (m + n + 12) % 12 }));

  return (
    <Card labelledBy="cal-h">
      <div className={s.head}>
        <h2 id="cal-h">{monthTitle(ym.y, ym.m)}</h2>
        <div className={s.nav}>
          <Button small icon="chevronLeft" onClick={() => shift(-1)} aria-label="Previous month">
            Previous
          </Button>
          <Button small onClick={() => setYm({ y: y0, m: m0 })}>
            Today
          </Button>
          <Button small onClick={() => shift(1)} aria-label="Next month">
            Next
          </Button>
        </div>
      </div>
      <div className={s.legend}>
        <span>
          <span className={s.swatch} style={{ background: "var(--critical)" }} />
          Within 48 hours
        </span>
        <span>
          <span className={s.swatch} style={{ background: "#f3d9b5" }} />
          This week
        </span>
        <span>
          <span className={s.swatch} style={{ background: "var(--accent-soft)" }} />
          Later
        </span>
      </div>
      <Async state={state} loadingLabel="Loading hearings">
        {(items) => {
          const byDay = new Map<string, CalendarItem[]>();
          for (const it of items) byDay.set(it.date, [...(byDay.get(it.date) ?? []), it]);
          const days = Array.from({ length: cells }, (_, i) => isoDate(ym.y, ym.m, i + 1 - lead));
          const monthDays = days.filter((d) => Number(d.slice(5, 7)) - 1 === ym.m && byDay.has(d));
          return (
            <>
              <div className={s.grid} role="table" aria-label={`Hearings in ${monthTitle(ym.y, ym.m)}`}>
                <div role="row" style={{ display: "contents" }}>
                  {DOW.map((d) => (
                    <div key={d} className={s.dow} role="columnheader">
                      {d}
                    </div>
                  ))}
                </div>
                {Array.from({ length: cells / 7 }, (_, w) => (
                  <div role="row" key={w} style={{ display: "contents" }}>
                    {days.slice(w * 7, w * 7 + 7).map((d) => {
                      const list = byDay.get(d) ?? [];
                      const outside = Number(d.slice(5, 7)) - 1 !== ym.m;
                      const band = list.length ? hearingBand(d) : null;
                      const cls = [s.cell, outside ? s.outside : "", d === today ? s.today : "", band === "critical" ? s.critical : band === "week" ? s.week : ""].join(" ");
                      return (
                        <div key={d} className={cls} role="cell" aria-label={`${fmtDate(d)}, ${list.length} ${list.length === 1 ? "hearing" : "hearings"}`}>
                          <span className={s.dayNo} aria-hidden="true">
                            {Number(d.slice(8, 10))}
                          </span>
                          {list.slice(0, PER_CELL).map((it) => (
                            <Link key={it.case.id} href={`/cases/${it.case.id}`} className={eventClass(it)} title={`${caseNumber(it.case)}: ${parties(it.case.petitioner, it.case.respondent)}${it.purpose ? ` (${it.purpose})` : ""}`}>
                              {caseNumber(it.case)}
                            </Link>
                          ))}
                          {list.length > PER_CELL ? <span className={s.more}>+{list.length - PER_CELL} more</span> : null}
                        </div>
                      );
                    })}
                  </div>
                ))}
              </div>
              <div className={s.agenda}>
                {monthDays.length === 0 ? <p className="muted">No hearings this month.</p> : null}
                {monthDays.map((d) => (
                  <div key={d} className={s.agendaDay}>
                    <span className={s.agendaDate}>{fmtDate(d)}</span>
                    {(byDay.get(d) ?? []).map((it) => (
                      <Link key={it.case.id} href={`/cases/${it.case.id}`} className={eventClass(it)} style={{ whiteSpace: "normal" }}>
                        {caseNumber(it.case)} · {parties(it.case.petitioner, it.case.respondent)}
                      </Link>
                    ))}
                  </div>
                ))}
              </div>
            </>
          );
        }}
      </Async>
    </Card>
  );
}
