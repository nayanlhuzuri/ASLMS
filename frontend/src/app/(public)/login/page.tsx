import type { Metadata } from "next";
import { Suspense } from "react";

import { LoginForm } from "@/components/auth/SignInForms";
import { T } from "@/lib/messages";

export const metadata: Metadata = { title: T.auth.signIn };

export default function Page() {
  return (
    <Suspense>
      <LoginForm />
    </Suspense>
  );
}
