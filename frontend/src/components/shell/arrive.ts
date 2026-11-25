/**
 * The one-time fade into the portal after the sign-in code (design home-page, decision 13): the code step writes the
 * flag just before it navigates, and the portal frame reads and removes it once on mount. A reload, a new tab or a
 * normal navigation finds no flag and shows no fade. Without sessionStorage nothing is written and nothing fades.
 */
export const ARRIVE_KEY = "aslms.arrive";

/** Marks the next portal mount for the arrival fade. */
export function markArrive(): void {
  try {
    sessionStorage.setItem(ARRIVE_KEY, "1");
  } catch {
    // storage unavailable: no fade, nothing else changes
  }
}

/** True once if the flag was set; the flag is removed either way. */
export function takeArrive(): boolean {
  try {
    const set = sessionStorage.getItem(ARRIVE_KEY) === "1";
    sessionStorage.removeItem(ARRIVE_KEY);
    return set;
  } catch {
    return false;
  }
}
