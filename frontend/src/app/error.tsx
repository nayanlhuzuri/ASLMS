"use client";

import Link from "next/link";

import { StatusPage } from "@/components/shell/StatusPage";
import { Button, buttonClass } from "@/components/ui";
import { T } from "@/lib/messages";

export default function ErrorPage({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <StatusPage
      alert
      title={T.errorTitle}
      text={T.errorText}
      actions={
        <>
          <Link href="/" className={buttonClass("secondary")}>
            {T.goHome}
          </Link>
          <Button onClick={reset}>{T.retry}</Button>
        </>
      }
    />
  );
}
