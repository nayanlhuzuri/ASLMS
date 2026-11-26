"use client";

/**
 * The Assistant picture's playing conversation (design home-page-refinements, decision 3). The whole conversation is
 * laid out once as a timeline of frames, each with how long it stays: the question typed into the ask box letter by
 * letter, then risen in as a bubble; the three-dot typing indicator; the answer written word by word with its source
 * markers; its Sources fading in. After the last answer the picture rests, the messages fade out and the timeline
 * starts again, in a loop until paused (about 17 s a round).
 *
 * `useSampleChat` plays it: one timer for the current frame, and none while paused, while the picture is less than a
 * third in view (IntersectionObserver; it holds and resumes where it was) or under reduced motion, where the finished
 * conversation shows at once and no button is offered. A browser without IntersectionObserver plays it whenever it is
 * shown. Nothing here makes a request.
 */
import { useEffect, useState, type RefObject } from "react";

import { usePrefersReducedMotion } from "@/components/ui/motion";

import type { SampleMessage } from "./sampleData";

/** What the picture shows at one moment. */
export interface ChatFrame {
  /** Messages in the thread; the last one may still be being written. */
  shown: number;
  /** Words of the last message shown when it is an answer being written; null: all of it. */
  words: number | null;
  /** The last answer's Sources are shown. */
  sources: boolean;
  /** The three-dot typing indicator after the messages. */
  typing: boolean;
  /** The text in the ask box ("" shows its placeholder). */
  ask: string;
  /** The messages are fading out before the conversation begins again. */
  fading: boolean;
}

export interface TimedFrame {
  frame: ChatFrame;
  ms: number;
}

/** The pace of the conversation, in milliseconds. */
export const CHAT_TIMING = {
  start: 400,
  letter: 28,
  afterTyped: 350,
  afterQuestion: 500,
  typing: 1200,
  word: 55,
  beforeSources: 150,
  afterAnswer: 1600,
  rest: 3500,
  fade: 450,
} as const;

const BLANK: ChatFrame = { shown: 0, words: null, sources: false, typing: false, ask: "", fading: false };

/** The finished conversation: every message, every answer whole with its Sources. */
export function finishedFrame(chat: readonly SampleMessage[]): ChatFrame {
  return { ...BLANK, shown: chat.length, sources: true };
}

export function wordsOf(text: string): string[] {
  return text.split(" ").filter(Boolean);
}

/** The timeline of one round, ending with the rest and the fade. */
export function chatTimeline(chat: readonly SampleMessage[], t = CHAT_TIMING): TimedFrame[] {
  const out: TimedFrame[] = [{ frame: BLANK, ms: t.start }];
  let shown = 0;
  for (const m of chat) {
    if (m.who === "q") {
      for (let i = 1; i <= m.text.length; i += 1) {
        out.push({ frame: { ...BLANK, shown, sources: true, ask: m.text.slice(0, i) }, ms: i === m.text.length ? t.afterTyped : t.letter });
      }
      shown += 1;
      out.push({ frame: { ...BLANK, shown, sources: true }, ms: t.afterQuestion });
    } else {
      out.push({ frame: { ...BLANK, shown, sources: true, typing: true }, ms: t.typing });
      shown += 1;
      const n = wordsOf(m.text).length;
      for (let w = 1; w <= n; w += 1) {
        out.push({ frame: { ...BLANK, shown, words: w }, ms: w === n ? t.beforeSources : t.word });
      }
      out.push({ frame: { ...BLANK, shown, sources: true }, ms: t.afterAnswer });
    }
  }
  const last = out[out.length - 1]!;
  last.ms = t.rest;
  out.push({ frame: { ...last.frame, fading: true }, ms: t.fade });
  return out;
}

/** The share of the picture that must be in view for the conversation to play. */
export const IN_VIEW_RATIO = 1 / 3;

function useInView(ref: RefObject<Element | null>): boolean {
  const [inView, setInView] = useState(() => typeof IntersectionObserver === "undefined");
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof IntersectionObserver === "undefined") return;
    const io = new IntersectionObserver(
      (entries) => {
        const entry = entries[entries.length - 1];
        if (entry) setInView(entry.isIntersecting && entry.intersectionRatio >= IN_VIEW_RATIO - 0.001);
      },
      { threshold: [0, IN_VIEW_RATIO] },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [ref]);
  return inView;
}

export interface SampleChat {
  frame: ChatFrame;
  paused: boolean;
  /** Reduced motion: the finished conversation, no button. */
  still: boolean;
  toggle: () => void;
}

export function useSampleChat(chat: readonly SampleMessage[], ref: RefObject<Element | null>): SampleChat {
  const still = usePrefersReducedMotion();
  const inView = useInView(ref);
  const [timeline] = useState(() => chatTimeline(chat));
  const [index, setIndex] = useState(0);
  const [paused, setPaused] = useState(false);
  const step = timeline[index] ?? timeline[0]!;
  const playing = !still && !paused && inView;

  useEffect(() => {
    if (!playing) return;
    const timer = setTimeout(() => setIndex((i) => (i + 1) % timeline.length), step.ms);
    return () => clearTimeout(timer);
  }, [playing, index, step.ms, timeline.length]);

  return {
    frame: still ? finishedFrame(chat) : step.frame,
    paused,
    still,
    toggle: () => setPaused((p) => !p),
  };
}
