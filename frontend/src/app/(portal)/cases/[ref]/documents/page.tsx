import { Documents } from "@/components/case/Documents";

export default async function Page({ params }: { params: Promise<{ ref: string }> }) {
  const { ref } = await params;
  return <Documents caseRef={decodeURIComponent(ref)} />;
}
