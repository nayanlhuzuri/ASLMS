/**
 * A one-time notice carried to the next page in this tab (design portal-workflow, decision 6: after sending a file
 * the sender no longer sees, the dashboard says so). Kept in sessionStorage; nothing secret is stored.
 */
const KEY = "aslms.flash";

export function setFlash(text: string): void {
  try {
    sessionStorage.setItem(KEY, text);
  } catch {
    // storage unavailable: the notice is lost, nothing else
  }
}

/** The notice waiting for this page, left in place (a render may run twice). */
export function peekFlash(): string | null {
  try {
    return typeof window === "undefined" ? null : sessionStorage.getItem(KEY);
  } catch {
    return null;
  }
}

export function clearFlash(): void {
  try {
    sessionStorage.removeItem(KEY);
  } catch {
    // nothing stored
  }
}
