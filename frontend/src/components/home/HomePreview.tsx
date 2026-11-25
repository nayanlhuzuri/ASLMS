/**
 * The home page's picture of the app (design home-page, decision 5): one framed window drawn in HTML and CSS with
 * plainly sample content, never live data and no request. On the left a Case Inbox ("With Me", three sample rows with
 * a party line, a hearing badge and a status word), on the right one Case Assistant question and answer with its source
 * marker and source chip. "Sample Case n" stands in for a case number and relative words for dates, so no identifier
 * is made up and the picture never goes out of date. It holds no live control: the window is `inert` and
 * `aria-hidden`, and the one `role="img"` around it names what it shows. Text wraps and is never cut short.
 */
import { Badge, type Tone } from "@/components/ui";
import { AssistantIcon, InboxIcon } from "@/components/shell/icons";
import { T } from "@/lib/messages";

import s from "./home.module.css";

/** The hearing badges' tones, by the meaning of row 190's colours: tomorrow is urgent, within a week is soon. */
const HEARING_TONES: (Tone | undefined)[] = ["danger", "warning", undefined];

export function HomePreview() {
  const P = T.home.preview;
  return (
    <div className={s.preview} role="img" aria-label={P.aria}>
      <div className={s.window} inert aria-hidden="true">
        <div className={s.windowBar}>
          <span className={s.windowDots}>
            <span />
            <span />
            <span />
          </span>
          <span className={s.windowLabel}>{P.windowLabel}</span>
        </div>
        <div className={s.panes}>
          <div className={s.inbox}>
            <p className={s.paneTitle}>
              <InboxIcon />
              <span>{P.inboxTitle}</span>
            </p>
            <ul className={s.rows}>
              {P.rows.map((row, i) => (
                <li key={row.name} className={s.row}>
                  <span className={s.rowText}>
                    <strong>{row.name}</strong>
                    <span>{P.party}</span>
                  </span>
                  <span className={s.rowBadges}>
                    <Badge tone={HEARING_TONES[i]} wrap>
                      {row.hearing}
                    </Badge>
                    <span className={s.status}>{row.status}</span>
                  </span>
                </li>
              ))}
            </ul>
          </div>
          <div className={s.assistant}>
            <p className={s.paneTitle}>
              <AssistantIcon />
              <span>{P.assistantTitle}</span>
            </p>
            <p className={s.question}>{P.question}</p>
            <p className={s.answer}>
              {P.answer} <span className={s.marker}>{P.marker}</span>
            </p>
            <p className={s.source}>{P.sourceChip}</p>
          </div>
        </div>
      </div>
    </div>
  );
}
