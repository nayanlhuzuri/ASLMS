import type { Metadata } from "next";
import type { ReactNode } from "react";

import { T } from "@/lib/messages";

export const metadata: Metadata = { title: T.inbox.title };

export default function InboxLayout({ children }: { children: ReactNode }) {
  return <>{children}</>;
}
