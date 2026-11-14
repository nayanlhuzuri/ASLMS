import type { Metadata } from "next";

import { AssistantPage } from "@/components/assistant/Assistant";
import { T } from "@/lib/messages";
import { plainParams } from "@/lib/params";

export const metadata: Metadata = { title: T.assistant.title };

type SP = Promise<Record<string, string | string[] | undefined>>;

// design assistant-ollama-work, decision 2: the tab in the address (`?tab=my-work`, `my-cases` or `court-orders`)
export default async function Page({ searchParams }: { searchParams: SP }) {
  return <AssistantPage tab={plainParams(await searchParams).tab ?? null} />;
}
