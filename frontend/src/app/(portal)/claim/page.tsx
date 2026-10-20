import { ClaimIndex } from "@/components/claim/ClaimFrame";
import { plainParams } from "@/lib/params";

type SP = Promise<Record<string, string | string[] | undefined>>;

export default async function Page({ searchParams }: { searchParams: SP }) {
  return <ClaimIndex params={plainParams(await searchParams)} />;
}
