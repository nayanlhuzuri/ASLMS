import type { Metadata } from "next";

import { AssistantPage } from "@/components/assistant/Assistant";
import { T } from "@/lib/messages";

export const metadata: Metadata = { title: T.assistant.title };

export default function Page() {
  return <AssistantPage />;
}
