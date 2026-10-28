/**
 * The next hearing badge (design next-hearing-highlight, decisions 1 and 4-9): one look for a case's next hearing on
 * every screen that shows one. The word comes first ("Today", "Tomorrow", "In 3 Days", "Date Passed"), then the date
 * in a `<time>`; colour is never the only signal and no `aria-label` replaces the visible words.
 * - strong (today, tomorrow): solid red; soft (2 to 7 days): amber; plain (later): no fill; warning (passed): the
 *   warning colour and icon on the neutral ground; muted (no date, disposed): greyed with a dashed border;
 * - `kind="suggested"` (a date read from an order and not yet confirmed): the band's colour as an outline, "Suggested"
 *   first;
 * - `size="sm"` (lists): the short date, and no word for the later band; `size="md"` (the case page and the modal):
 *   the weekday and date, always with the word for a future date;
 * - never truncated: the word and the date are two unbreakable parts that wrap onto a second line in a narrow cell.
 * It does not reuse `Badge`, whose text is ellipsised.
 */
import { formatDate, weekdayDate } from "@/lib/format";
import { hearingBand, hearingTone, hearingWords, type HearingKind, type HearingSize } from "@/lib/hearingDate";
import { T } from "@/lib/messages";

import s from "./hearingDate.module.css";

function WarningIcon() {
  return (
    <svg className={s.icon} aria-hidden="true" width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round">
      <path d="M8 1.8 15 14H1z" />
      <path d="M8 6.2v3.6M8 11.6v.4" strokeLinecap="round" />
    </svg>
  );
}

export function HearingDate({
  date,
  status,
  kind = "firm",
  size = "sm",
  showDate = true,
  now,
}: {
  date: string | null | undefined;
  /** The case status: "disposed" reads Disposed in place of any stored date. */
  status?: string | null;
  kind?: HearingKind;
  size?: HearingSize;
  /** False gives the word alone (the dashboard list, where the date chip already shows the date). */
  showDate?: boolean;
  now?: Date;
}) {
  const { band, days } = hearingBand(date, { status, now });
  const tone = hearingTone(band);
  const dated = band !== "none" && band !== "disposed" && !!date;
  // the word alone must never be empty, so without the date the later band reads its countdown
  const suggested = kind === "suggested" && dated;
  // the band's own word; "Suggested" is drawn before it with a separator hidden from screen readers
  const word = hearingWords(band, days, { kind: "firm", size: showDate ? size : "md" });
  const lead = suggested ? T.hearing.badges.suggested : null;
  const title = suggested ? T.hearing.suggestedHint : band === "passed" ? T.hearing.passedHint : undefined;
  const withDate = dated && showDate;
  return (
    <span
      className={`${s.root} ${s[tone]} ${size === "md" ? s.md : s.sm}`}
      data-band={band}
      data-kind={suggested ? "suggested" : "firm"}
      title={title}
    >
      {lead || word ? (
        <span className={s.word}>
          {band === "passed" ? <WarningIcon /> : null}
          {lead}
          {lead && word ? (
            <span className={s.sep} aria-hidden="true">
              {" · "}
            </span>
          ) : null}
          {word}
        </span>
      ) : null}
      {(lead || word) && withDate ? (
        <span className={s.sep} aria-hidden="true">
          {" · "}
        </span>
      ) : null}
      {withDate && date ? (
        <time className={s.date} dateTime={date}>
          {size === "md" ? weekdayDate(date) : formatDate(date)}
        </time>
      ) : null}
    </span>
  );
}
