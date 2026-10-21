import type { ReactNode } from "react";

import { AuthFrame } from "@/components/auth/AuthFrame";

/** The sign-in, code and reset pages in the split-panel frame (design portal-ui-redesign, decision 26, template A). */
export default function PublicLayout({ children }: { children: ReactNode }) {
  return <AuthFrame>{children}</AuthFrame>;
}
