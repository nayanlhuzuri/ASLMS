import type { Metadata } from "next";
import { Suspense } from "react";

import { ProfileStepForm } from "@/components/auth/WelcomeForms";
import { T } from "@/lib/messages";

export const metadata: Metadata = { title: T.auth.welcomeProfileTitle };

export default function Page() {
  return (
    <Suspense>
      <ProfileStepForm />
    </Suspense>
  );
}
