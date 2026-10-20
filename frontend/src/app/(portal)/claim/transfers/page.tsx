import { ClaimFrame } from "@/components/claim/ClaimFrame";
import { plainParams } from "@/lib/params";

type SP = Promise<Record<string, string | string[] | undefined>>;

export default async function Page({ searchParams }: { searchParams: SP }) {
  return <ClaimFrame tab="transfers" params={plainParams(await searchParams)} />;
}
