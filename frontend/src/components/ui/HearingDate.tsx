/**
 * The next hearing badge (design next-hearing-highlight, decisions 1 and 4-9): one look for a case's next hearing on
 * every screen that shows one. The word comes first ("Today", "Tomorrow", "In 3 Days", "Date Passed"), then the date
 * in a `<time>`; colour is never the only signal and no `aria-label` replaces the visible words.
 * - strong (today, tomorrow): solid red; soft (2 to 7 days): amber; plain (later): no fill; warning (passed): the
 *   warning colour and icon on the neutral ground; muted (no date, disposed): greyed with a dashed border;
 * - `kind="suggested"` (a date read from an order and not yet confirmed): the band's colour as an outline, "Suggested"
 *   first;
 * - `kind="around"` (design next-date-direct, decision 8: a period, qualified or returnable date read from the latest
 *   order, shown directly): "Around" first, in the band's normal fill, with the owner's sentence as the title and, in
 *   the medium size, as a muted line ("Around 11 Mar 2026 (after 3 weeks, order of 18 Feb 2026)");
 * - `next`: the case's one next hearing from the server (`NextHearingOut`), giving the date and the kind; with an order
 *   date that differs from the court's record, the "Order Differs" chip (`data-differs="true"`) with the sentence as its
 *   title, and in the medium size the basis line and the sentence under the badge;
 * - `size="sm"` (lists): the short date, and no word for the later band; `size="md"` (the case page and the modal):
 *   the weekday and date, always with the word for a future date;
 * - never truncated: the word and the date are two unbreakable parts that wrap onto a second line in a narrow cell.
 * It does not reuse `Badge`, whose text is ellipsised.
 */
import { formatDate, weekdayDate } from "@/lib/format";
import {
  aroundSentence,
  basisLine,
  differsSentence,
  hearingBand,
  hearingTone,
  hearingWords,
  nextHearingProps,
  type HearingKind,
  type HearingSize,
  type NextHearing,
} from "@/lib/hearingDate";
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
  next,
  status,
  kind,
  size = "sm",
  showDate = true,
  lines,
  now,
}: {
  /** A date with no basis (the calendar, the dashboard); `next` wins when given. */
  date?: string | null | undefined;
  /** The case's one next hearing from the server (design next-date-direct); `null` reads No Date Yet. */
  next?: NextHearing | null;
  /** The case status: "disposed" reads Disposed in place of any stored date. */
  status?: string | null;
  kind?: HearingKind;
  size?: HearingSize;
  /** False gives the word alone (the dashboard list, where the date chip already shows the date). */
  showDate?: boolean;
  /** The muted lines under the badge (basis, discrepancy); by default in the medium size when `next` is given. */
  lines?: boolean;
  now?: Date;
}) {
  const fromNext = next !== undefined ? nextHearingProps(next) : null;
  const shown = fromNext ? fromNext.date : (date ?? null);
  const shownKind: HearingKind = kind ?? fromNext?.kind ?? "firm";
  const { band, days } = hearingBand(shown, { status, now });
  const tone = hearingTone(band);
  const dated = band !== "none" && band !== "disposed" && !!shown;
  // the word alone must never be empty, so without the date the later band reads its countdown
  const lead =
    dated && shownKind === "suggested" ? T.hearing.badges.suggested : dated && shownKind === "around" ? T.hearing.badges.around : null;
  // the band's own word; "Suggested" or "Around" is drawn before it with a separator hidden from screen readers
  const word = hearingWords(band, days, { kind: "firm", size: showDate ? size : "md" });
  const around = dated && shownKind === "around" ? aroundSentence(next) : null;
  const title =
    dated && shownKind === "suggested"
      ? T.hearing.suggestedHint
      : around
        ? around
        : band === "passed"
          ? T.hearing.passedHint
          : undefined;
  const withDate = dated && showDate;
  const differs = band !== "disposed" ? differsSentence(next) : null;
  const badge = (
    <span
      className={`${s.root} ${s[tone]} ${size === "md" ? s.md : s.sm}`}
      data-band={band}
      data-kind={dated && shownKind !== "firm" ? shownKind : "firm"}
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
      {withDate && shown ? (
        <time className={s.date} dateTime={shown}>
          {size === "md" ? weekdayDate(shown) : formatDate(shown)}
        </time>
      ) : null}
    </span>
  );
  const showLines = (lines ?? (size === "md" && next !== undefined)) && dated;
  const basis = showLines ? basisLine(next) : null;
  if (!differs && !basis) return badge;
  return (
    <span className={s.wrap}>
      <span className={s.top}>
        {badge}
        {differs ? (
          <span className={s.differs} data-differs="true" title={differs}>
            {T.hearing.badges.differs}
          </span>
        ) : null}
      </span>
      {basis ? <span className={s.line}>{basis}</span> : null}
      {showLines && differs ? <span className={s.line}>{differs}</span> : null}
    </span>
  );
}
