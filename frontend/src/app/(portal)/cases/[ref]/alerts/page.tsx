import { CaseAlerts } from "@/components/workflow/CaseAlerts";

export default async function Page({ params }: { params: Promise<{ ref: string }> }) {
  const { ref } = await params;
  return <CaseAlerts caseRef={decodeURIComponent(ref)} />;
}
