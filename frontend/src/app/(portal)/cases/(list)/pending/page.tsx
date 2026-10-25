import { Held } from "@/components/files/Held";
import { plainParams } from "@/lib/params";

type SP = Promise<Record<string, string | string[] | undefined>>;

export default async function Page({ searchParams }: { searchParams: SP }) {
  return <Held tab="pending" params={plainParams(await searchParams)} />;
}
