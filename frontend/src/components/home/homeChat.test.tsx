/**
 * The Assistant picture's playing conversation (design home-page-refinements, decision 3): it plays in order (the
 * question typed into the ask box, its bubble, the typing indicator, the answer word by word, its Sources), Pause stops
 * it and Play resumes it, it begins again after the last answer, it holds while the picture is out of view, and under
 * reduced motion all four messages show at once with no button.
 */
import { act, fireEvent, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { T } from "@/lib/messages";
import { renderWithClient } from "@/test/render";

import { CHAT_TIMING, chatTimeline, finishedFrame, IN_VIEW_RATIO, wordsOf } from "./homeChat";
import { HomeSamples } from "./HomeSamples";
import { SAMPLE_CHAT } from "./sampleData";

const S = T.home.samples;
const ROUND = chatTimeline(SAMPLE_CHAT).reduce((n, f) => n + f.ms, 0);

function motion(reduced: boolean) {
  vi.stubGlobal(
    "matchMedia",
    vi.fn((query: string) => ({
      matches: query.includes("reduce") ? reduced : false,
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  );
}

/** A stand-in IntersectionObserver whose one instance the test moves in and out of view. */
let observed: ((entries: Partial<IntersectionObserverEntry>[]) => void) | null = null;
class FakeObserver {
  constructor(cb: (entries: Partial<IntersectionObserverEntry>[]) => void) {
    observed = cb;
  }
  observe() {}
  disconnect() {}
  unobserve() {}
  takeRecords() {
    return [];
  }
}

function view(ratio: number) {
  act(() => observed?.([{ isIntersecting: ratio > 0, intersectionRatio: ratio }]));
}

/** Moves the clock in small steps, letting React render and arm the next frame's timer after each. */
function play(ms: number, step = 2) {
  for (let t = 0; t < ms; t += step) {
    act(() => {
      vi.advanceTimersByTime(step);
    });
  }
}

const chatWindow = () => screen.getByRole("img", { name: S.assistantAria }).firstElementChild as HTMLElement;
const messages = () => [...chatWindow().querySelectorAll("[data-chat]")].map((m) => m.getAttribute("data-chat"));
const askText = () => chatWindow().querySelector("[data-typed]")?.textContent ?? "";
const answerText = (i: number) => chatWindow().querySelectorAll("[data-chat='answer'] p")[i]?.textContent ?? "";
const sources = () => chatWindow().querySelectorAll("[data-chat-sources]").length;

beforeEach(() => {
  vi.useFakeTimers();
  observed = null;
  vi.stubGlobal("IntersectionObserver", FakeObserver);
  motion(false);
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("the timeline", () => {
  it("lasts about 15 to 20 seconds a round and ends with the rest and the fade", () => {
    expect(ROUND).toBeGreaterThanOrEqual(15_000);
    expect(ROUND).toBeLessThanOrEqual(20_000);
    const timeline = chatTimeline(SAMPLE_CHAT);
    expect(timeline[timeline.length - 2]!.ms).toBe(CHAT_TIMING.rest);
    expect(timeline[timeline.length - 1]!.frame.fading).toBe(true);
    expect(timeline[timeline.length - 1]!.ms).toBe(CHAT_TIMING.fade);
  });

  it("the conversation is two questions and two answers, each answer citing its sources by marker", () => {
    expect(SAMPLE_CHAT.map((m) => m.who)).toEqual(["q", "a", "q", "a"]);
    for (const m of SAMPLE_CHAT) {
      if (m.who !== "a") continue;
      for (const src of m.sources) expect(m.text).toContain(`[${src.label}]`);
    }
  });
});

describe("the conversation plays (decision 3)", () => {
  it("waits until a third of the picture is in view, then plays in order: typed question, bubble, typing, words, Sources", () => {
    renderWithClient(<HomeSamples />);
    expect(screen.getByRole("button", { name: S.pauseLabel })).toBeInTheDocument();
    play(2_000);
    expect(messages()).toEqual([]);
    view(IN_VIEW_RATIO / 2);
    play(2_000);
    expect(messages()).toEqual([]);
    view(IN_VIEW_RATIO);

    const q1 = SAMPLE_CHAT[0]!.text;
    play(CHAT_TIMING.start + CHAT_TIMING.letter * 10);
    expect(askText().length).toBeGreaterThan(0);
    expect(q1.startsWith(askText())).toBe(true);
    expect(messages()).toEqual([]);

    play(CHAT_TIMING.letter * q1.length + CHAT_TIMING.afterTyped);
    expect(messages()).toEqual(["question"]);
    expect(askText()).toBe("");

    play(CHAT_TIMING.afterQuestion);
    expect(messages()).toEqual(["question", "typing"]);

    play(CHAT_TIMING.typing + CHAT_TIMING.word * 3);
    expect(messages()).toEqual(["question", "answer"]);
    const partial = answerText(0);
    expect(partial.length).toBeGreaterThan(0);
    expect(partial.length).toBeLessThan(SAMPLE_CHAT[1]!.text.length - 10);
    expect(sources()).toBe(0);

    play(CHAT_TIMING.word * wordsOf(SAMPLE_CHAT[1]!.text).length + CHAT_TIMING.beforeSources);
    expect(sources()).toBe(1);
    expect(answerText(0)).not.toContain("[S1]");
    expect(answerText(0)).toContain("S1");
  });

  it("Pause stops it at any point and Play resumes it", () => {
    renderWithClient(<HomeSamples />);
    view(1);
    play(CHAT_TIMING.start + CHAT_TIMING.letter * 8);
    fireEvent.click(screen.getByRole("button", { name: S.pauseLabel }));
    const held = askText();
    expect(held.length).toBeGreaterThan(0);
    play(5_000);
    expect(askText()).toBe(held);
    expect(messages()).toEqual([]);
    const button = screen.getByRole("button", { name: S.playLabel });
    expect(button).toHaveTextContent(S.play);
    fireEvent.click(button);
    expect(screen.getByRole("button", { name: S.pauseLabel })).toHaveTextContent(S.pause);
    play(CHAT_TIMING.letter * SAMPLE_CHAT[0]!.text.length + CHAT_TIMING.afterTyped);
    expect(messages()).toEqual(["question"]);
  });

  it("plays to the end, rests, fades and begins again", () => {
    renderWithClient(<HomeSamples />);
    view(1);
    const timeline = chatTimeline(SAMPLE_CHAT);
    const toRest = timeline.slice(0, -2).reduce((n, f) => n + f.ms, 0);
    play(toRest + 500);
    expect(messages()).toEqual(["question", "answer", "question", "answer"]);
    expect(sources()).toBe(2);
    play(CHAT_TIMING.rest);
    expect(chatWindow().querySelector("[data-fading]")).not.toBeNull();
    play(CHAT_TIMING.fade + 100);
    expect(messages()).toEqual([]);
    expect(chatWindow().querySelector("[data-fading]")).toBeNull();
    play(CHAT_TIMING.start + CHAT_TIMING.letter * 5);
    expect(askText().length).toBeGreaterThan(0);
  });

  it("holds while the picture is out of view and resumes where it was", () => {
    renderWithClient(<HomeSamples />);
    view(1);
    play(CHAT_TIMING.start + CHAT_TIMING.letter * SAMPLE_CHAT[0]!.text.length + CHAT_TIMING.afterTyped + 50);
    expect(messages()).toEqual(["question"]);
    view(0);
    play(10_000);
    expect(messages()).toEqual(["question"]);
    view(1);
    play(CHAT_TIMING.afterQuestion + 50);
    expect(messages()).toEqual(["question", "typing"]);
  });
});

describe("under reduced motion (decision 3)", () => {
  it("shows the finished conversation at once, with every answer's Sources and no button", () => {
    motion(true);
    renderWithClient(<HomeSamples />);
    expect(messages()).toEqual(["question", "answer", "question", "answer"]);
    expect(sources()).toBe(2);
    expect(askText()).toBe("");
    expect(screen.queryByRole("button", { name: S.pauseLabel })).toBeNull();
    expect(screen.queryByRole("button", { name: S.playLabel })).toBeNull();
    play(5_000);
    expect(messages()).toEqual(["question", "answer", "question", "answer"]);
    expect(finishedFrame(SAMPLE_CHAT)).toMatchObject({ shown: 4, words: null, sources: true, typing: false, fading: false });
  });
});
