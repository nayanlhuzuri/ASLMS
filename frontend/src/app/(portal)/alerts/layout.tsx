import type { Metadata } from "next";
import type { ReactNode } from "react";

import { AlertsFrame } from "@/components/alerts/AlertsFrame";
import { T } from "@/lib/messages";

export const metadata: Metadata = { title: T.alerts.title };

export default function AlertsLayout({ children }: { children: ReactNode }) {
  return <AlertsFrame>{children}</AlertsFrame>;
}
