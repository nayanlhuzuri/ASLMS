"use client";

/**
 * The home page's sign-in card (design home-page, decisions 2, 11 and 12). The step is read from the address:
 * `/login?step=code` (with `next` kept) is the code step, anything else the password step. The card changes step with
 * `window.history.pushState`, which Next.js keeps `useSearchParams` in step with, so the page neither remounts nor asks
 * the server for anything; browser Back and Forward change the address and so the step, and a reload keeps it.
 *
 * Both steps sit in one grid cell. On a change the incoming step fades in from 12 px aside while the outgoing one, kept
 * mounted for `DURATION.med` by `usePresence`, fades out the other way, `inert` and `aria-hidden` meanwhile; going back
 * reverses the directions. After a change the step's first field takes the focus. Under reduced motion the swap is
 * instant and only one step is ever mounted. The forms keep their fields, checks, errors, resend countdown and calls.
 *
 * The card also installs the page's one click listener for the Sign In links (`jumpToSignIn.ts`).
 */
import { useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { CodeForm, LoginForm } from "@/components/auth/SignInForms";
import { buttonClass } from "@/components/ui";
import { DURATION, usePresence } from "@/components/ui/motion";
import { T } from "@/lib/messages";
import { safeNext } from "@/lib/safeNext";

import s from "./home.module.css";
import { activeField, listenForSignInLinks, SIGN_IN_ID } from "./jumpToSignIn";

type Step = "password" | "code";
type Direction = "forward" | "back";

function stepOf(params: URLSearchParams | { get(name: string): string | null }): Step {
  return params.get("step") === "code" ? "code" : "password";
}

/** The home page's address for a step, keeping `next` (and `expired` when the code ran out). */
export function stepAddress(step: Step, next: string, expired = false): string {
  const query = new URLSearchParams();
  if (step === "code") query.set("step", "code");
  if (expired) query.set("expired", "1");
  if (next && next !== "/") query.set("next", next);
  const text = query.toString();
  return text ? `/login?${text}` : "/login";
}

export function SignInCard() {
  const params = useSearchParams();
  const next = safeNext(params.get("next"));
  const urlStep = stepOf(params);
  const [step, setStep] = useState<Step>(urlStep);
  const [seen, setSeen] = useState<Step>(urlStep);
  const [dir, setDir] = useState<Direction>("forward");
  // a change has happened: the incoming step animates and takes the focus (never on the first load)
  const [moves, setMoves] = useState(0);
  const cardRef = useRef<HTMLDivElement>(null);

  function show(to: Step) {
    if (to === step) return;
    setDir(to === "code" ? "forward" : "back");
    setStep(to);
    setMoves((n) => n + 1);
  }

  if (urlStep !== seen) {
    // Back, Forward or any other change of the address (React's documented derived-state pattern)
    setSeen(urlStep);
    show(urlStep);
  }

  const password = usePresence(step === "password", DURATION.med);
  const code = usePresence(step === "code", DURATION.med);

  useEffect(() => listenForSignInLinks(), []);

  useEffect(() => {
    if (moves === 0 || !cardRef.current) return;
    activeField(cardRef.current)?.focus();
  }, [moves]);

  function phase(p: { closing: boolean }): "enter" | "leave" | undefined {
    if (p.closing) return "leave";
    return moves > 0 ? "enter" : undefined;
  }

  function stepProps(p: { closing: boolean }, name: Step) {
    return {
      className: s.step,
      "data-step": name,
      "data-phase": phase(p),
      "data-dir": dir,
      inert: p.closing || undefined,
      "aria-hidden": p.closing || undefined,
    };
  }

  return (
    <div id={SIGN_IN_ID} ref={cardRef} className={s.card}>
      <div className={s.stack}>
        {password.mounted ? (
          <div {...stepProps(password, "password")}>
            <LoginForm
              headingLevel="h2"
              onSent={() => {
                window.history.pushState(null, "", stepAddress("code", next));
                show("code");
              }}
            />
          </div>
        ) : null}
        {code.mounted ? (
          <div {...stepProps(code, "code")}>
            <CodeForm
              headingLevel="h2"
              onStartAgain={() => {
                window.history.pushState(null, "", stepAddress("password", next));
                show("password");
              }}
              onExpired={() => {
                window.history.replaceState(null, "", stepAddress("password", next, true));
                show("password");
              }}
            />
          </div>
        ) : null}
      </div>
    </div>
  );
}

/** A Sign In link of the top bar or the closing band: a secondary button-styled link to the card. */
export function SignInLink() {
  return (
    <a href={`#${SIGN_IN_ID}`} className={buttonClass("secondary")}>
      {T.auth.signIn}
    </a>
  );
}
