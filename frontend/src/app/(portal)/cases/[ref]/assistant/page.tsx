import { CaseAssistant } from "@/components/assistant/Assistant";

export default async function Page({ params }: { params: Promise<{ ref: string }> }) {
  const { ref } = await params;
  return <CaseAssistant caseRef={decodeURIComponent(ref)} />;
}
