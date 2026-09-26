"use client";

import { AssistantChat } from "@/components/case/detail/AssistantChat";
import { PageHeader } from "@/components/ui/Layout";

export default function ResearchPage() {
  return (
    <>
      <PageHeader title="Research" sub="Ask SourceTrace about past orders and the Acts, rules and policies, without a particular case." />
      <AssistantChat />
    </>
  );
}
