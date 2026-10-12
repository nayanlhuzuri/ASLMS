import { Notes } from "@/components/case/Notes";

export default async function Page({ params }: { params: Promise<{ ref: string }> }) {
  const { ref } = await params;
  return <Notes caseRef={decodeURIComponent(ref)} />;
}
