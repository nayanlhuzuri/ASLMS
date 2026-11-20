import type { Metadata } from "next";

import { InsightsPage } from "@/components/insights/InsightsPage";
import { T } from "@/lib/messages";
import { plainParams } from "@/lib/params";

export const metadata: Metadata = { title: T.insights.title };

type SP = Promise<Record<string, string | string[] | undefined>>;

export default async function Page({ searchParams }: { searchParams: SP }) {
  return <InsightsPage params={plainParams(await searchParams)} />;
}
