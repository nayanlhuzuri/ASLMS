import type { Metadata } from "next";
import type { ReactNode } from "react";

import { ReportsFrame } from "@/components/reports/ReportsFrame";
import { T } from "@/lib/messages";

export const metadata: Metadata = { title: T.reports.title };

export default function ReportsLayout({ children }: { children: ReactNode }) {
  return <ReportsFrame>{children}</ReportsFrame>;
}
