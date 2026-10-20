import type { Metadata } from "next";
import type { ReactNode } from "react";

import { T } from "@/lib/messages";

export const metadata: Metadata = { title: T.claim.title };

export default function ClaimLayout({ children }: { children: ReactNode }) {
  return <>{children}</>;
}
