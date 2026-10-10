import type { Metadata } from "next";
import { Suspense } from "react";

import { CodeForm } from "@/components/auth/SignInForms";
import { T } from "@/lib/messages";

export const metadata: Metadata = { title: T.auth.codeTitle };

export default function Page() {
  return (
    <Suspense>
      <CodeForm />
    </Suspense>
  );
}
