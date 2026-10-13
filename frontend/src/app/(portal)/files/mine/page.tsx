import { Held } from "@/components/files/Held";
import { plainParams } from "@/lib/params";

type SP = Promise<Record<string, string | string[] | undefined>>;

export default async function Page({ searchParams }: { searchParams: SP }) {
  return <Held scope="me" params={plainParams(await searchParams)} />;
}
