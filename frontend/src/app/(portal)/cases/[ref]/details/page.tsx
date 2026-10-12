import { Details } from "@/components/case/Details";

export default async function Page({ params }: { params: Promise<{ ref: string }> }) {
  const { ref } = await params;
  return <Details caseRef={decodeURIComponent(ref)} />;
}
