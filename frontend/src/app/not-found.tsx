"use client";

// a client component: it calls buttonClass(), which lives in the client UI kit
import Link from "next/link";

import { StatusPage } from "@/components/shell/StatusPage";
import { buttonClass } from "@/components/ui";
import { T } from "@/lib/messages";

export default function NotFound() {
  return (
    <StatusPage
      title={T.notFound}
      text={T.notFoundText}
      actions={
        <Link href="/" className={buttonClass("primary")}>
          {T.goHome}
        </Link>
      }
    />
  );
}
