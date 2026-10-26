import { OfficeDetailView } from "@/components/admin/Offices";
import { plainParams } from "@/lib/params";

type SP = Promise<Record<string, string | string[] | undefined>>;

// design office-head-picker, decision 8: `?reactivate=1` opens the Reactivate dialog again, `?head=<id>` puts the new
// person in its picker (back from New User)
export default async function Page({ params, searchParams }: { params: Promise<{ code: string }>; searchParams: SP }) {
  const { code } = await params;
  const query = plainParams(await searchParams);
  return <OfficeDetailView code={decodeURIComponent(code)} reactivate={query.reactivate === "1"} head={query.head} />;
}
