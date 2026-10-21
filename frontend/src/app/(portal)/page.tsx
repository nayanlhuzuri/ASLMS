import type { Metadata } from "next";

import { Dashboard } from "@/components/dashboard/Dashboard";
import { T } from "@/lib/messages";
import { plainParams } from "@/lib/params";

export const metadata: Metadata = { title: T.dash.title };

type SP = Promise<Record<string, string | string[] | undefined>>;

export default async function DashboardPage({ searchParams }: { searchParams: SP }) {
  return <Dashboard params={plainParams(await searchParams)} />;
}
