import type { Metadata } from "next";

import { Dashboard } from "@/components/dashboard/Dashboard";
import { T } from "@/lib/messages";

export const metadata: Metadata = { title: T.dash.title };

export default function DashboardPage() {
  return <Dashboard />;
}
