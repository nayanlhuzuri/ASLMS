import type { ReactNode } from "react";

import { AuthFrame } from "@/components/auth/AuthFrame";
import { SessionWatch } from "@/components/shell/SessionWatch";

/**
 * The first-sign-in pages in the same frame, with a wider form side (decision 26, template A). A signed-in session,
 * so the session watch runs here too (design session-timeout, decision 20).
 */
export default function WelcomeLayout({ children }: { children: ReactNode }) {
  return (
    <AuthFrame wide>
      {children}
      <SessionWatch />
    </AuthFrame>
  );
}
