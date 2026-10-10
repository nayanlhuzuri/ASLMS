import { OfficeDetailView } from "@/components/admin/Offices";

export default async function Page({ params }: { params: Promise<{ code: string }> }) {
  const { code } = await params;
  return <OfficeDetailView code={decodeURIComponent(code)} />;
}
