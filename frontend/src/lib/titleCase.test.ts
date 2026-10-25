/** The Title Case helper (design portal-ui-polish-2, decision 2): the same pinned examples as the pytest. */
import { describe, expect, it } from "vitest";

import { ACRONYMS, SMALL_WORDS, isTitleCase, titleCase } from "./titleCase";

const PINNED: [string, string][] = [
  // the mockup's Before and After table
  ["Case inbox", "Case Inbox"],
  ["Sent by me", "Sent by Me"],
  ["Send case", "Send Case"],
  ["user types", "User Types"],
  ["Napix call log", "NAPIX Call Log"],
  // the note's own examples
  ["Working on", "Working On"],
  ["Search the court", "Search the Court"],
  ["Include logins without an active office", "Include Logins Without an Active Office"],
  ["Court search / discovery", "Court Search / Discovery"],
];

describe("titleCase", () => {
  it.each(PINNED)("%s → %s", (before, after) => {
    expect(titleCase(before)).toBe(after);
    expect(isTitleCase(after)).toBe(true);
    expect(isTitleCase(before)).toBe(false);
  });

  it("keeps small words lower in the middle, capitalised first and last", () => {
    expect(titleCase("the case of the day")).toBe("The Case of the Day");
    expect(titleCase("what it is for")).toBe("What It Is For");
    expect(titleCase("Sign In To")).toBe("Sign in To");
    expect(titleCase("A Case")).toBe("A Case");
    for (const w of ["a", "an", "the", "and", "or", "of", "by", "to", "in", "on", "for", "at", "with"]) {
      expect(SMALL_WORDS.has(w)).toBe(true);
    }
  });

  it("capitalises From and Without", () => {
    expect(titleCase("changed from default")).toBe("Changed From Default");
    expect(titleCase("cases without owner")).toBe("Cases Without Owner");
  });

  it("keeps acronyms in capitals", () => {
    expect(titleCase("cnr and pdf")).toBe("CNR and PDF");
    expect(titleCase("court apis")).toBe("Court APIs");
    expect(titleCase("Court APIs")).toBe("Court APIs");
    expect(titleCase("otp sent by sms")).toBe("OTP Sent by SMS");
    expect(titleCase("aslms services")).toBe("ASLMS Services");
    expect(titleCase("napix json url")).toBe("NAPIX JSON URL");
    expect(titleCase("ist ip id csv ai njdg")).toBe("IST IP ID CSV AI NJDG");
    expect(ACRONYMS.cnr).toBe("CNR");
  });

  it("capitalises only the first part of a hyphenated word", () => {
    expect(titleCase("sign-in off")).toBe("Sign-in Off");
    expect(titleCase("e-mail")).toBe("E-mail");
    expect(titleCase("read office-only notes")).toBe("Read Office-only Notes");
    expect(titleCase("include sub-offices")).toBe("Include Sub-offices");
  });

  it("splits segments at slash, middle dot, dash and colon", () => {
    expect(titleCase("search / the court")).toBe("Search / The Court");
    expect(titleCase("hearings · by date")).toBe("Hearings · By Date");
    expect(titleCase("cause list: the day")).toBe("Cause List: The Day");
    expect(titleCase("load — of the day")).toBe("Load — Of the Day");
  });

  it("leaves words with digits or inner capitals alone", () => {
    expect(titleCase("wp(c) 24h")).toBe("Wp(c) 24h");
    expect(titleCase("the WP(C) list")).toBe("The WP(C) List");
    expect(titleCase("use cURL and eCourts")).toBe("Use cURL and eCourts");
    expect(titleCase("last 7days")).toBe("Last 7days");
  });

  it("keeps punctuation around a word", () => {
    expect(titleCase("(retired) the day")).toBe("(Retired) the Day");
    expect(titleCase("what is it?")).toBe("What Is It?");
    expect(titleCase('"quoted" word')).toBe('"Quoted" Word');
    expect(titleCase("the  double space")).toBe("The  Double Space");
    expect(titleCase("")).toBe("");
  });
});
