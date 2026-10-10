import type { Metadata } from "next";
import { Suspense } from "react";

import { ForgotCodeForm } from "@/components/auth/SignInForms";
import { T } from "@/lib/messages";

export const metadata: Metadata = { title: T.auth.forgotTitle };

export default function Page() {
  return (
    <Suspense>
      <ForgotCodeForm />
    </Suspense>
  );
}
