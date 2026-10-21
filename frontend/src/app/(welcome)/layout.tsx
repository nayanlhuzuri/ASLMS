import type { ReactNode } from "react";

import { AuthFrame } from "@/components/auth/AuthFrame";

/** The first-sign-in pages in the same frame, with a wider form side (decision 26, template A). */
export default function WelcomeLayout({ children }: { children: ReactNode }) {
  return <AuthFrame wide>{children}</AuthFrame>;
}
