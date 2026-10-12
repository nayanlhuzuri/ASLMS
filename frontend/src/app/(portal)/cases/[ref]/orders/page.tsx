import { Orders } from "@/components/case/Orders";

export default async function Page({ params }: { params: Promise<{ ref: string }> }) {
  const { ref } = await params;
  return <Orders caseRef={decodeURIComponent(ref)} />;
}
