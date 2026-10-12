import { Overview } from "@/components/case/Overview";

export default async function Page({ params }: { params: Promise<{ ref: string }> }) {
  const { ref } = await params;
  return <Overview caseRef={decodeURIComponent(ref)} />;
}
