import { Timeline } from "@/components/case/Timeline";

export default async function Page({ params }: { params: Promise<{ ref: string }> }) {
  const { ref } = await params;
  return <Timeline caseRef={decodeURIComponent(ref)} />;
}
