import { Links } from "@/components/case/Links";

export default async function Page({ params }: { params: Promise<{ ref: string }> }) {
  const { ref } = await params;
  return <Links caseRef={decodeURIComponent(ref)} />;
}
