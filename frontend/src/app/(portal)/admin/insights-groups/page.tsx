import { InsightsGroups } from "@/components/admin/InsightsGroups";
import { plainParams } from "@/lib/params";

type SP = Promise<Record<string, string | string[] | undefined>>;

export default async function Page({ searchParams }: { searchParams: SP }) {
  return <InsightsGroups params={plainParams(await searchParams)} />;
}
