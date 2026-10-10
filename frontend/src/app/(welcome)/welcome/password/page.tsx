import type { Metadata } from "next";
import { Suspense } from "react";

import { PasswordStepForm } from "@/components/auth/WelcomeForms";
import { T } from "@/lib/messages";

export const metadata: Metadata = { title: T.auth.welcomePasswordTitle };

export default function Page() {
  return (
    <Suspense>
      <PasswordStepForm />
    </Suspense>
  );
}
