"use client";

/**
 * The home page's two sample pictures (design home-page-refinements, decisions 3 to 5): the Case Inbox's With Me tab
 * and a Case Assistant conversation, each a framed picture that looks exactly like the live portal because it is drawn
 * with the portal's own pieces (the kit's `DataTable`, `HearingDate` and `Badge`, the inbox's `CaseCell` and
 * `ActionDueCell`, the shell's icons and the Assistant's own styles and marker reader) fed with the static sample data
 * of `sampleData.ts`. Each picture's window is `inert` and `aria-hidden` inside one `role="img"` whose label says what
 * it shows; it holds no link, field or button and makes no request. The caption bar above each window says "Sample
 * Data"; the Assistant's caption bar also holds the Pause / Play button of its playing conversation (WCAG 2.2.2), not
 * offered under reduced motion, where the finished conversation shows.
 *
 * The side menu is narrower than the live one, and the From column is left out when the picture is narrower than about
 * 860 px (a container query), so every column fits beside the Assistant; on a phone the table is cards, as the real
 * `DataTable` draws it.
 */
import { Fragment, useRef } from "react";

import a from "@/components/assistant/assistant.module.css";
import { ActionDueCell, CaseCell, Chevron, closureMark } from "@/components/inbox/rows";
import { AssistantIcon, BellIcon, NAV_ICONS, PauseIcon, PlayIcon, SearchIcon } from "@/components/shell/icons";
import { Badge, DataTable, HearingDate, ListCount, type Column } from "@/components/ui";
import uiLayout from "@/components/ui/layout.module.css";
import { markers } from "@/lib/assistant";
import { T } from "@/lib/messages";

import { useSampleChat, wordsOf, type ChatFrame } from "./homeChat";
import s from "./home.module.css";
import { SAMPLE_CHAT, SAMPLE_NOW, SAMPLE_ROWS, type SampleMessage, type SampleRow, type SampleSource } from "./sampleData";

const S = T.home.samples;

function SampleLabel() {
  return <span className={s.sampleLabel}>{S.sampleLabel}</span>;
}

/* ---------- the Case Inbox picture ---------- */

/** The side menu's entries in the picture, with the sample counts the live menu shows as pills. */
const SIDE: { group: string; entries: { key: string; label: string; count?: number; current?: boolean }[] }[] = [
  {
    group: T.nav.groups.work,
    entries: [
      { key: "dashboard", label: T.nav.dashboard },
      { key: "inbox", label: T.nav.inbox, count: SAMPLE_ROWS.length, current: true },
      { key: "claim", label: T.nav.claim, count: 12 },
      { key: "causelist", label: T.nav.causelist },
      { key: "calendar", label: T.nav.calendar },
      { key: "alerts", label: T.nav.alerts, count: 3 },
      { key: "search", label: T.nav.search },
      { key: "assistant", label: T.nav.assistant },
    ],
  },
  { group: T.nav.groups.oversight, entries: [{ key: "reports", label: T.nav.reports }] },
];

const INBOX_TABS = [T.tabs.inbox.withMe, T.tabs.inbox.mine, T.tabs.inbox.sent, T.tabs.inbox.department];

const COLUMNS: Column<SampleRow>[] = [
  {
    key: "case",
    header: T.files.case,
    primary: true,
    cell: (r) => (
      <CaseCell
        c={{ case_no_text: r.caseNo, ref_no: r.caseNo, cnr: null, petitioner_summary: r.petitioner, respondent_summary: r.respondent }}
        marks={[r.isNew ? { label: T.cases.lead.new, tone: "info" } : null, closureMark({ status: r.status, closed: false })]}
      />
    ),
  },
  { key: "next", header: T.inbox.nextHearingCol, cell: (r) => <HearingDate date={r.next} status={r.status} now={SAMPLE_NOW} /> },
  { key: "action", header: T.files.action, cell: (r) => <ActionDueCell action={r.action} due={r.due} /> },
  { key: "who", header: T.cases.from, cell: (r) => <span data-sample-from="">{r.from}</span> },
  { key: "open", header: <span className="visually-hidden">{T.files.details}</span>, hideOnPhone: true, width: "var(--s6)", cell: () => <Chevron /> },
];

function SampleInbox() {
  return (
    <div className={s.shot} data-shot="inbox">
      <div className={s.shotCap}>
        <span className={s.shotTitle}>{S.inboxTitle}</span>
        <SampleLabel />
      </div>
      <div className={s.shotBody} role="img" aria-label={S.inboxAria}>
        <div className={`${s.window} ${s.app}`} inert aria-hidden="true">
          <div className={s.appTop}>
            <span className={s.appBrand}>
              <span className={s.appGov}>{T.owner}</span>
              <span className={s.appName}>{T.portal}</span>
            </span>
            <span className={s.appSearch}>
              <SearchIcon size={14} />
              <span>{T.search.box}</span>
            </span>
            <span className={s.appBell}>
              <BellIcon size={16} />
            </span>
            <span className={s.appAvatar} />
          </div>
          <div className={s.appBody}>
            <div className={s.appSide}>
              {SIDE.map((g) => (
                <div key={g.group} className={s.sideGroup}>
                  <span className={s.sideLabel}>{g.group}</span>
                  {g.entries.map((e) => {
                    const Icon = NAV_ICONS[e.key];
                    return (
                      <span key={e.key} className={s.sideRow} data-current={e.current ? "" : undefined}>
                        <span className={s.sideIcon}>{Icon ? <Icon /> : null}</span>
                        <span className={s.sideText}>{e.label}</span>
                        {e.count ? <span className={s.sideCount}>{e.count}</span> : null}
                      </span>
                    );
                  })}
                </div>
              ))}
            </div>
            <div className={s.appMain}>
              <span className={s.appCrumb}>{T.nav.inbox}</span>
              <span className={s.appTitle}>{T.inbox.myTitle}</span>
              <span className={s.appSubtitle}>{T.inbox.mySubtitle}</span>
              <div className={`${uiLayout.tabs} ${s.appTabs}`} data-scroll-x="">
                {INBOX_TABS.map((label, i) => (
                  <span key={label} className={uiLayout.tab} data-current={i === 0 ? "" : undefined}>
                    {label}
                    {i === 0 ? <span className={uiLayout.tabCount}>{SAMPLE_ROWS.length}</span> : null}
                  </span>
                ))}
              </div>
              <div className={s.appToolbar}>
                <span className={s.appField}>
                  <span className={s.appFieldLabel}>{T.filters.wordsShort}</span>
                  <span className={s.appInput} />
                </span>
                <span className={s.appField}>
                  <span className={s.appFieldLabel}>{T.cases.show}</span>
                  <span className={s.appSwitch}>
                    <span data-on="">{T.cases.showMe}</span>
                    <span>{T.cases.showOffices}</span>
                  </span>
                </span>
                <span className={s.appCount}>
                  <ListCount shown={SAMPLE_ROWS.length} noun={T.inbox.casesNoun} nounOne={T.inbox.caseNoun} searching={false} />
                </span>
              </div>
              <div className={s.appTable}>
                <DataTable caption={T.files.captionMine} columns={COLUMNS} rows={SAMPLE_ROWS} rowKey={(r) => r.key} />
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ---------- the Case Assistant picture ---------- */

const A = T.assistant;
const CASE_TABS = [T.tabs.case.overview, T.tabs.case.orders, T.tabs.case.notes, T.tabs.case.assistant];

/** An answer's text up to `words` words (null: all), with its `[S1]` markers drawn as the Assistant draws them. */
function MarkedSample({ text, words }: { text: string; words: number | null }) {
  const shown = words === null ? text : wordsOf(text).slice(0, words).join(" ");
  return (
    <p className={a.text}>
      {markers(shown).map((seg, i) =>
        seg.label ? (
          <span key={i} className={a.marker}>
            {seg.label}
          </span>
        ) : (
          <Fragment key={i}>{seg.text}</Fragment>
        ),
      )}
    </p>
  );
}

function SampleSources({ sources }: { sources: SampleSource[] }) {
  return (
    <div className={s.chatSources} data-chat-sources="">
      <p className={a.group}>{A.courtGroup}</p>
      <ul className={a.sources}>
        {sources.map((src) => (
          <li key={src.label} className={a.source}>
            <span className={a.num}>{src.label}</span>
            <div className={a.sourceBody}>
              <span className={a.kindLine}>{src.kind}</span>
              <span className={a.sourceTitle}>{src.title}</span>
              <blockquote className={a.passage}>“{src.passage}”</blockquote>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

function ChatMessage({ m, words, sources }: { m: SampleMessage; words: number | null; sources: boolean }) {
  if (m.who === "q") {
    return (
      <div className={`${a.msg} ${s.chatMsg}`} data-chat="question">
        <div className={a.who}>{A.you}</div>
        <div className={a.bubble}>
          <div className={a.question}>{m.text}</div>
        </div>
      </div>
    );
  }
  return (
    <div className={`${a.msg} ${s.chatMsg}`} data-chat="answer">
      <div className={a.who}>{A.answerBy.ollama}</div>
      <div className={a.bubble}>
        <div className={a.answer}>
          <div className={a.answerHead}>
            <Badge tone="info">{A.localModel}</Badge>
            <span>{A.outcomes.answered}</span>
          </div>
          <MarkedSample text={m.text} words={words} />
          {sources ? <SampleSources sources={m.sources} /> : null}
        </div>
      </div>
    </div>
  );
}

function ChatThread({ frame }: { frame: ChatFrame }) {
  const shown = SAMPLE_CHAT.slice(0, frame.shown);
  return (
    <div className={s.chatThread} data-fading={frame.fading ? "" : undefined}>
      {shown.map((m, i) => {
        const writing = i === shown.length - 1;
        return <ChatMessage key={i} m={m} words={writing ? frame.words : null} sources={writing ? frame.sources : true} />;
      })}
      {frame.typing ? (
        <div className={`${a.msg} ${s.chatMsg}`} data-chat="typing">
          <div className={a.who}>{A.answerBy.ollama}</div>
          <div className={a.bubble}>
            <span className={s.typing}>
              <span />
              <span />
              <span />
            </span>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function SampleAssistant() {
  const body = useRef<HTMLDivElement>(null);
  const chat = useSampleChat(SAMPLE_CHAT, body);
  const { frame } = chat;
  return (
    <div className={`${s.shot} ${s.chatShot}`} data-shot="assistant">
      <div className={s.shotCap}>
        <span className={s.shotTitle}>{S.assistantTitle}</span>
        <span className={s.shotTools}>
          {chat.still ? null : (
            <button type="button" className={s.playBtn} aria-label={chat.paused ? S.playLabel : S.pauseLabel} onClick={chat.toggle}>
              {chat.paused ? <PlayIcon /> : <PauseIcon />}
              <span>{chat.paused ? S.play : S.pause}</span>
            </button>
          )}
          <SampleLabel />
        </span>
      </div>
      <div className={s.shotBody} role="img" aria-label={S.assistantAria} ref={body}>
        <div className={`${s.window} ${s.chat}`} inert aria-hidden="true" data-frame={frame.shown}>
          <span className={s.appCrumb}>
            {SAMPLE_ROWS[0]!.caseNo} / {T.tabs.case.assistant}
          </span>
          <div className={`${uiLayout.tabs} ${s.appTabs}`} data-scroll-x="">
            {CASE_TABS.map((label, i) => (
              <span key={label} className={uiLayout.tab} data-current={i === CASE_TABS.length - 1 ? "" : undefined}>
                {label}
              </span>
            ))}
          </div>
          <ChatThread frame={frame} />
          <div className={s.askBox}>
            <span className={s.askText} data-typed={frame.ask ? "" : undefined}>
              {frame.ask || A.questionPlaceholder}
              {frame.ask ? <span className={s.caret} /> : null}
            </span>
            <span className={s.askButton}>
              <AssistantIcon />
              {A.ask}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}

/** The two pictures side by side from 1024 px (the Case Inbox wider), stacked below. */
export function HomeSamples() {
  return (
    <div className={s.shots}>
      <SampleInbox />
      <SampleAssistant />
    </div>
  );
}
