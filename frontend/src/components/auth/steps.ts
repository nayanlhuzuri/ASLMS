/**
 * What the sign-in pages pass from one step to the next: the masked address and the timings the server returned.
 * Nothing secret (the challenge id stays in its httpOnly cookie); kept in sessionStorage for the tab only.
 */
const KEY = "aslms.step";

export interface StoredStep {
  sent_to?: string;
  expires_in?: number;
  resend_after?: number;
  at: number;
}

export function saveStep(step: Omit<StoredStep, "at">): void {
  try {
    sessionStorage.setItem(KEY, JSON.stringify({ ...step, at: Date.now() }));
  } catch {
    // storage unavailable: the code page shows the generic text
  }
}

export function loadStep(): StoredStep | null {
  try {
    const raw = sessionStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as StoredStep) : null;
  } catch {
    return null;
  }
}

export function clearStep(): void {
  try {
    sessionStorage.removeItem(KEY);
  } catch {
    // nothing stored
  }
}

/** Seconds left before a new code may be asked for. */
export function resendLeft(step: StoredStep | null, now = Date.now()): number {
  if (!step?.resend_after) return 0;
  return Math.max(0, Math.ceil(step.resend_after - (now - step.at) / 1000));
}

/** The page after the code, by the server's `next_step`, carrying `next`. */
export function afterSignIn(nextStep: string | undefined, next: string): string {
  const carry = next && next !== "/" ? `?next=${encodeURIComponent(next)}` : "";
  if (nextStep === "change_password") return `/welcome/password${carry}`;
  if (nextStep === "confirm_profile") return `/welcome/profile${carry}`;
  return next || "/";
}
