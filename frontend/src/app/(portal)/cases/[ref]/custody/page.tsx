import { CustodyTab } from "@/components/workflow/CustodyTab";

export default async function Page({ params }: { params: Promise<{ ref: string }> }) {
  const { ref } = await params;
  return <CustodyTab caseRef={decodeURIComponent(ref)} />;
}
