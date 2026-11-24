import type { Metadata } from "next";

import { AssistantPage } from "@/components/assistant/Assistant";
import { T } from "@/lib/messages";
import { plainParams } from "@/lib/params";

export const metadata: Metadata = { title: T.assistant.title };

type SP = Promise<Record<string, string | string[] | undefined>>;

// design assistant-ollama-work, decision 2: the tab in the address (`?tab=my-work`, `my-cases` or `court-orders`);
// design research-index-portal, decision 8: the tab's filters beside it
export default async function Page({ searchParams }: { searchParams: SP }) {
  const params = plainParams(await searchParams);
  return <AssistantPage tab={params.tab ?? null} params={params} />;
}
