/**
 * Pure helpers of the System health screen (design api-health-checker, decision 15): the court cards' combined 24 h
 * answered rate, the typical response, the status tones, the seconds until the next test is allowed and the plain
 * reason a "Test now" button is disabled. Every figure comes from the API; nothing here decides a status.
 */
import type { ApiCard, HealthStatus, SystemHealth } from "./api/types";
import { T } from "./messages";

export type Tone = "success" | "warning" | "danger" | undefined;

export function toneOf(status: HealthStatus | string | null | undefined): Tone {
  if (status === "ok") return "success";
  if (status === "warn") return "warning";
  if (status === "down") return "danger";
  return undefined;
}

/** `98 %`, or `—` without a rate. */
export function percent(rate: number | null | undefined): string {
  return typeof rate === "number" ? `${Math.round(rate * 100)} %` : "—";
}

export function cardsOf(data: SystemHealth | undefined): ApiCard[] {
  return data ? data.groups.flatMap((g) => g.cards) : [];
}

/** The court cards' 24 h calls and answered, summed. */
export function courtTotals(cards: ApiCard[]): { calls: number; answered: number; rate: number | null } {
  const calls = cards.reduce((n, c) => n + c.h24.calls, 0);
  const answered = cards.reduce((n, c) => n + c.h24.answered, 0);
  return { calls, answered, rate: calls ? answered / calls : null };
}

/** The median of the cards' 24 h medians (cards with calls only); null when no card has one. */
export function typicalMs(cards: ApiCard[]): number | null {
  const values = cards.map((c) => c.h24.p50_ms).filter((v): v is number => typeof v === "number").sort((a, b) => a - b);
  if (values.length === 0) return null;
  const mid = Math.floor(values.length / 2);
  return values.length % 2 ? values[mid]! : Math.round((values[mid - 1]! + values[mid]!) / 2);
}

/** Whole seconds until `at` (0 when past or missing). */
export function secondsUntil(at: string | null | undefined, now: number = Date.now()): number {
  if (!at) return 0;
  const ms = new Date(at).getTime() - now;
  return ms > 0 ? Math.ceil(ms / 1000) : 0;
}

/** Why "Test now" is disabled on a card (null: it may be pressed): the switch, then the wait for the next allowed
 * test (counted down here; once past, the server checks again), then the server's reason (no sample held). */
export function testBlock(card: ApiCard, napixEnabled: boolean, now: number = Date.now()): string | null {
  if (!napixEnabled) return card.test.reason ?? T.system.switchedOff;
  if (card.test.next_allowed_at) {
    const wait = secondsUntil(card.test.next_allowed_at, now);
    return wait > 0 ? T.system.nextIn(wait) : null;
  }
  return card.test.available ? null : (card.test.reason ?? null);
}

/** The worst of the court cards in the overall ring's tone: a court card counts at most as `warn`. */
export function ringTone(rate: number | null): "ok" | "warn" | "down" | "unknown" {
  if (rate === null) return "unknown";
  if (rate >= 0.9) return "ok";
  return rate >= 0.5 ? "warn" : "down";
}
