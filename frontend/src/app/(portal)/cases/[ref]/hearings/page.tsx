import { Hearings } from "@/components/case/Hearings";

export default async function Page({ params }: { params: Promise<{ ref: string }> }) {
  const { ref } = await params;
  return <Hearings caseRef={decodeURIComponent(ref)} />;
}
