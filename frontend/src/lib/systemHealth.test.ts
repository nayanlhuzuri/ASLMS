import { describe, expect, it } from "vitest";

import type { ApiCard } from "./api/types";
import { courtTotals, percent, ringTone, secondsUntil, testBlock, toneOf, typicalMs } from "./systemHealth";

function card(extra: Partial<ApiCard> = {}): ApiCard {
  return {
    key: "state",
    label: "High Courts List",
    label_key: "high_courts",
    group: "masters",
    status: "ok",
    status_word: "Working",
    last_call: null,
    h24: { calls: 10, answered: 9, failed: 1, rate: 0.9, p50_ms: 500, p95_ms: 900 },
    d7: { calls: 10, answered: 9, failed: 1, rate: 0.9 },
    hours: [],
    test: { available: true, reason: null, cost: 1, next_allowed_at: null },
    last_test: null,
    ...extra,
  };
}

describe("the System health helpers", () => {
  it("tones, percents and the ring", () => {
    expect([toneOf("ok"), toneOf("warn"), toneOf("down"), toneOf("unknown")]).toEqual(["success", "warning", "danger", undefined]);
    expect(percent(0.9833)).toBe("98 %");
    expect(percent(null)).toBe("—");
    expect([ringTone(null), ringTone(0.95), ringTone(0.7), ringTone(0.2)]).toEqual(["unknown", "ok", "warn", "down"]);
  });

  it("totals and the typical response across cards", () => {
    const cards = [card(), card({ h24: { calls: 0, answered: 0, failed: 0, rate: null, p50_ms: null, p95_ms: null } }), card({ h24: { calls: 30, answered: 15, failed: 15, rate: 0.5, p50_ms: 1500, p95_ms: 2000 } })];
    expect(courtTotals(cards)).toEqual({ calls: 40, answered: 24, rate: 0.6 });
    expect(typicalMs(cards)).toBe(1000);
    expect(typicalMs([])).toBeNull();
    expect(courtTotals([]).rate).toBeNull();
  });

  it("why Test now is disabled", () => {
    const now = Date.parse("2026-10-21T09:00:00Z");
    expect(testBlock(card(), true, now)).toBeNull();
    expect(testBlock(card({ test: { available: false, reason: "off", cost: 1, next_allowed_at: null } }), false, now)).toBe("off");
    expect(testBlock(card({ test: { available: false, reason: "No stored order PDF yet", cost: 1, next_allowed_at: null } }), true, now)).toBe(
      "No stored order PDF yet",
    );
    const soon = card({ test: { available: false, reason: "wait", cost: 1, next_allowed_at: "2026-10-21T09:00:40Z" } });
    expect(testBlock(soon, true, now)).toBe("Next test possible in 40 s");
    expect(testBlock(soon, true, now + 41_000)).toBeNull();
    expect(secondsUntil(null, now)).toBe(0);
    expect(secondsUntil("2026-10-21T09:00:00.500Z", now)).toBe(1);
  });
});
