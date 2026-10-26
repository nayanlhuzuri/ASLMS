"use client";

/**
 * The date of the Cause list screen.
 *
 * `DateHero` is the left zone of Layout B (design portal-ui-polish-2, decisions 23-25): the weekday over the date, large;
 * Previous Day and Next Day as icon buttons with accessible names; Pick Date opening the browser's own date picker
 * (`showPicker`, focus as the fallback); the "Lists Held: n" badge counting the day's lists from `GET /causelists/{date}`
 * ("No Lists" in amber when there are none); and View Cause List under it, enabled once a bench is chosen.
 *
 * `DayNotice` is the day's state when no list is held (design portal-causelist, decisions 4 and 5): the state's banner
 * with "Previous List" and "Next List" to the nearest dates with lists, and, on a day not loaded, failed or without a
 * list, "Fetch this day from the court" for holders of `admin.napix_refetch` (the existing `POST
 * /admin/napix/refetch/day`); its 409 `already_held` asks before resending with `force`. Nobody else sees the button.
 */
import { useQueryClient } from "@tanstack/react-query";
import { useId, useRef, useState } from "react";

import { Badge, Button, Dialog, ErrorBanner, Notice } from "@/components/ui";
import { api, ApiError } from "@/lib/api/client";
import { CAUSELISTS_KEY } from "@/lib/api/hooks";
import type { CauselistDay } from "@/lib/api/types";
import { FETCHABLE_STATES } from "@/lib/causelist";
import { addDays, formatDate, formatNumber, formatWeekday } from "@/lib/format";
import { T } from "@/lib/messages";
import { useAction } from "@/lib/useAction";

import s from "./causelist.module.css";

/** The number of lists the day holds (none unless the day's state is `held`). */
export function listsHeld(day: CauselistDay | undefined): number {
  if (!day || day.state !== "held") return 0;
  return day.totals.lists;
}

function Chevron({ back }: { back?: boolean }) {
  return (
    <svg aria-hidden="true" width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2">
      <path d={back ? "m10 4-4 4 4 4" : "m6 4 4 4-4 4"} />
    </svg>
  );
}

export function DateHero({
  date,
  day,
  canView,
  onDate,
  onView,
}: {
  date: string;
  day: CauselistDay | undefined;
  /** A bench is chosen, so View Cause List is enabled. */
  canView: boolean;
  onDate: (date: string) => void;
  onView: () => void;
}) {
  const picker = useRef<HTMLInputElement>(null);
  const hintId = useId();
  const held = listsHeld(day);

  function pick() {
    const input = picker.current;
    if (!input) return;
    try {
      input.showPicker();
    } catch {
      input.focus();
    }
  }

  return (
    <div className={s.dateHero}>
      <span className={s.heroCaption}>{T.causelist.listDate}</span>
      <span className={s.heroDay}>{formatWeekday(date)}</span>
      <span className={s.heroDate} aria-live="polite">
        {formatDate(date)}
      </span>
      <div className={s.heroNav}>
        <Button variant="secondary" className={s.iconButton} aria-label={T.causelist.previousDay} title={T.causelist.previousDay} onClick={() => onDate(addDays(date, -1))}>
          <Chevron back />
        </Button>
        <Button variant="secondary" onClick={pick}>
          {T.causelist.pickDate}
        </Button>
        <Button variant="secondary" className={s.iconButton} aria-label={T.causelist.nextDay} title={T.causelist.nextDay} onClick={() => onDate(addDays(date, 1))}>
          <Chevron />
        </Button>
        <input
          ref={picker}
          type="date"
          className={s.pickInput}
          tabIndex={-1}
          aria-hidden="true"
          data-testid="pick-date"
          value={date}
          onChange={(e) => {
            if (e.target.value) onDate(e.target.value);
          }}
        />
      </div>
      <span className={s.heroBadge}>
        {held > 0 ? <Badge tone="info">{T.causelist.listsHeld(formatNumber(held))}</Badge> : <Badge tone="warning">{T.causelist.noLists}</Badge>}
      </span>
      <div className={s.heroView}>
        <Button variant="secondary" disabled={!canView} aria-describedby={canView ? undefined : hintId} onClick={onView}>
          {T.causelist.viewListButton}
        </Button>
        {canView ? null : (
          <span id={hintId} className={s.heroHint}>
            {T.causelist.viewListHint}
          </span>
        )}
      </div>
    </div>
  );
}

export function DayNotice({
  date,
  day,
  canFetch,
  onDate,
}: {
  date: string;
  day: CauselistDay | undefined;
  canFetch: boolean;
  onDate: (date: string) => void;
}) {
  const queryClient = useQueryClient();
  const action = useAction();
  const [queued, setQueued] = useState(false);
  const [held, setHeld] = useState<string | null>(null);

  async function fetchDay(force: boolean) {
    setQueued(false);
    setHeld(null);
    const out = await action.run(() =>
      api<unknown>("/admin/napix/refetch/day", { method: "POST", body: force ? { date, force: true } : { date } }).then(
        () => true,
        (err) => {
          if (err instanceof ApiError && err.status === 409 && err.code === "already_held") {
            setHeld(T.causelist.heldText(String(err.extra.status ?? ""), Number(err.extra.lists_stored ?? 0)));
            return false;
          }
          throw err;
        },
      ),
    );
    if (out.ok && out.value) {
      setQueued(true);
      await queryClient.invalidateQueries({ queryKey: CAUSELISTS_KEY });
    }
  }

  const state = day?.state;
  const banner = state && state !== "held" ? T.causelist.banners[state] : null;
  if (!banner && !queued && !action.error && held === null) return null;
  return (
    <section className="stack" aria-label={T.causelist.date}>
      {banner ? (
        <Notice>
          <span>{banner}</span>{" "}
          <span className={s.noticeActions}>
            {day?.previous_date ? (
              <Button variant="link" onClick={() => onDate(day.previous_date!)}>
                {T.causelist.previousList}
              </Button>
            ) : null}
            {day?.next_date ? (
              <Button variant="link" onClick={() => onDate(day.next_date!)}>
                {T.causelist.nextList}
              </Button>
            ) : null}
            {canFetch && state && FETCHABLE_STATES.includes(state) ? (
              <Button variant="secondary" busy={action.busy} onClick={() => void fetchDay(false)}>
                {T.causelist.fetchDay}
              </Button>
            ) : null}
          </span>
        </Notice>
      ) : null}
      {queued ? <Notice>{T.causelist.fetchQueued}</Notice> : null}
      <ErrorBanner error={action.error} />
      <Dialog open={held !== null} title={T.causelist.heldTitle} onClose={() => setHeld(null)}>
        <p>{held}</p>
        <div className="actions">
          <Button busy={action.busy} onClick={() => void fetchDay(true)}>
            {T.causelist.fetchAnyway}
          </Button>
          <Button variant="secondary" onClick={() => setHeld(null)}>
            {T.cancel}
          </Button>
        </div>
      </Dialog>
    </section>
  );
}
