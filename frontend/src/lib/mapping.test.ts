import { describe, expect, it } from "vitest";

import { ApiError } from "./api/client";
import { changedFields, given, isCnr, isRootOffice, officeRequired, scoringErrors, weightBody } from "./mapping";

const VALID = { counsel_code: 0.9, counsel_code_partial: 0.6, name_pattern: 0.6, watchlist: 0.95, linked_case: 0.5, keyword: 0.4, strong: 0.85, possible: 0.5 };

describe("isCnr", () => {
  it("accepts four letters and twelve digits after trim and upper case", () => {
    expect(isCnr("ASHC010012342025")).toBe(true);
    expect(isCnr("  ashc010012342025 ")).toBe(true);
  });

  it("refuses wrong lengths and characters in the wrong places", () => {
    expect(isCnr("ASHC01001234202")).toBe(false); // 15
    expect(isCnr("ASHC0100123420251")).toBe(false); // 17
    expect(isCnr("AS1C010012342025")).toBe(false); // a digit in the first four
    expect(isCnr("ASHC01001234202X")).toBe(false); // a letter in the last twelve
    expect(isCnr("")).toBe(false);
  });
});

describe("weightBody", () => {
  it("omits the key when the input was not changed", () => {
    expect(weightBody(false, "0.5")).toEqual({});
    expect("weight" in weightBody(false, "")).toBe(false);
  });

  it("sends null on clear and a number on set", () => {
    expect(weightBody(true, "")).toEqual({ weight: null });
    expect(weightBody(true, null)).toEqual({ weight: null });
    expect(weightBody(true, "0.75")).toEqual({ weight: 0.75 });
  });
});

describe("isRootOffice", () => {
  it("is the office whose path has no slash", () => {
    expect(isRootOffice({ path: "GOA" })).toBe(true);
    expect(isRootOffice({ path: "GOA/EDU" })).toBe(false);
    expect(isRootOffice(undefined)).toBe(false);
  });
});

describe("scoringErrors", () => {
  it("accepts valid values, a weight of 1 and Strong at 1", () => {
    expect(scoringErrors(VALID)).toEqual({});
    expect(scoringErrors({ ...VALID, keyword: 1, strong: 1 })).toEqual({});
  });

  it("refuses a weight of 0 or above 1", () => {
    expect(scoringErrors({ ...VALID, keyword: 0 }).keyword).toBeTruthy();
    expect(scoringErrors({ ...VALID, keyword: 1.001 }).keyword).toBeTruthy();
    expect(scoringErrors({ ...VALID, watchlist: "" }).watchlist).toBeTruthy();
  });

  it("refuses Possible equal to or above Strong", () => {
    expect(scoringErrors({ ...VALID, possible: 0.85 }).possible).toBeTruthy();
    expect(scoringErrors({ ...VALID, possible: 0.9 }).possible).toBeTruthy();
  });

  it("keeps the partial code weight inside the possible band and below the counsel code weight", () => {
    const band = "The partial code weight must be at least Possible and below Strong.";
    const below = "The partial code weight must be below the counsel code weight.";
    expect(scoringErrors({ ...VALID, counsel_code_partial: 0.5 })).toEqual({});
    expect(scoringErrors({ ...VALID, counsel_code_partial: 0.45 }).counsel_code_partial).toBe(band);
    expect(scoringErrors({ ...VALID, counsel_code_partial: 0.85 }).counsel_code_partial).toBe(band);
    expect(scoringErrors({ ...VALID, possible: 0.7 }).counsel_code_partial).toBe(band);
    expect(scoringErrors({ ...VALID, counsel_code_partial: 0.95, strong: 0.99 }).counsel_code_partial).toBe(below);
    expect(scoringErrors({ ...VALID, counsel_code_partial: 0.9, strong: 0.99 }).counsel_code_partial).toBe(below);
    expect(scoringErrors({ ...VALID, counsel_code_partial: "" }).counsel_code_partial).toBe("Enter a number greater than 0 and at most 1.");
  });
});

describe("changedFields", () => {
  const v = (weights: Partial<typeof VALID>) => {
    const all = { ...VALID, ...weights };
    return {
      weights: { counsel_code: all.counsel_code, counsel_code_partial: all.counsel_code_partial, name_pattern: all.name_pattern, watchlist: all.watchlist, linked_case: all.linked_case, keyword: all.keyword },
      thresholds: { strong: all.strong, possible: all.possible },
    };
  };

  it("marks only the values that differ from the next older version", () => {
    expect(changedFields(v({ keyword: 0.45, strong: 0.8 }), v({}))).toEqual(["keyword", "strong"]);
    expect(changedFields(v({}), v({}))).toEqual([]);
    expect(changedFields(v({}), null)).toEqual([]);
  });

  it("marks the partial code weight against a version written before it existed", () => {
    const old = v({});
    delete (old.weights as Record<string, number>).counsel_code_partial;
    expect(changedFields(v({}), old)).toEqual(["counsel_code_partial"]);
  });
});

describe("given", () => {
  it("shows the API's message for a refusal, keeps other errors", () => {
    const refused = given(new ApiError(403, "forbidden", "the office is outside your offices")) as ApiError;
    expect(refused.code).toBe("bad_input");
    expect(refused.message).toBe("the office is outside your offices");
    const signedOut = new ApiError(401, "signed_out", "x");
    expect(given(signedOut)).toBe(signedOut);
  });

  it("recognises the office_code refusal of the watchlist", () => {
    expect(officeRequired(new ApiError(400, "bad_request", "office_code is required: you work in 2 departments"))).toBe(true);
    expect(officeRequired(new ApiError(400, "bad_request", "no such office"))).toBe(false);
  });
});
