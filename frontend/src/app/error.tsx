"use client";

import Link from "next/link";

import { T } from "@/lib/messages";

export default function ErrorPage({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <main id="main" style={{ padding: 48, maxWidth: 640, margin: "0 auto" }} role="alert">
      <h1>{T.errorTitle}</h1>
      <p>
        <button type="button" onClick={reset}>
          {T.retry}
        </button>{" "}
        <Link href="/">{T.goHome}</Link>
      </p>
    </main>
  );
}
