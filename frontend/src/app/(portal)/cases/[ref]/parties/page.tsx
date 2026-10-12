import { Parties } from "@/components/case/Parties";

export default async function Page({ params }: { params: Promise<{ ref: string }> }) {
  const { ref } = await params;
  return <Parties caseRef={decodeURIComponent(ref)} />;
}
