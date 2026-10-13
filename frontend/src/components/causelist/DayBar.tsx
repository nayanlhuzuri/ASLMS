"use client";

/**
 * The date of the Cause list screen (design portal-causelist, decisions 4 and 5): any date, "Previous list" and "Next
 * list" to the nearest dates with lists, and the day's state. On a day not loaded, failed or without a list, holders of
 * `admin.napix_refetch` see "Fetch this day from the court" (the existing `POST /admin/napix/refetch/day`); its 409
 * `already_held` asks before resending with `force`. Nobody else sees the button.
 */
import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Button, Dialog, ErrorBanner, Notice, TextField } from "@/components/ui";
import { api, ApiError } from "@/lib/api/client";
import { CAUSELISTS_KEY } from "@/lib/api/hooks";
import type { CauselistDay } from "@/lib/api/types";
import { FETCHABLE_STATES } from "@/lib/causelist";
import { T } from "@/lib/messages";
import { useAction } from "@/lib/useAction";

import s from "./causelist.module.css";

export function DayBar({
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
  return (
    <section className="stack" aria-label={T.causelist.date}>
      <div className={s.bar}>
        <TextField
          label={T.causelist.date}
          type="date"
          value={date}
          onChange={(e) => {
            if (e.target.value) onDate(e.target.value);
          }}
        />
        <Button variant="secondary" disabled={!day?.previous_date} onClick={() => day?.previous_date && onDate(day.previous_date)}>
          {T.causelist.previousList}
        </Button>
        <Button variant="secondary" disabled={!day?.next_date} onClick={() => day?.next_date && onDate(day.next_date)}>
          {T.causelist.nextList}
        </Button>
        {state === "held" ? <span className={s.state}>{T.causelist.states.held}</span> : null}
      </div>
      {banner ? (
        <Notice>
          <span>{banner}</span>{" "}
          {canFetch && state && FETCHABLE_STATES.includes(state) ? (
            <Button variant="secondary" busy={action.busy} onClick={() => void fetchDay(false)}>
              {T.causelist.fetchDay}
            </Button>
          ) : null}
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
