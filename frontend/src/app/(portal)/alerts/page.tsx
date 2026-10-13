import { AlertList } from "@/components/alerts/AlertList";
import { plainParams } from "@/lib/params";

type SP = Promise<Record<string, string | string[] | undefined>>;

export default async function Page({ searchParams }: { searchParams: SP }) {
  return <AlertList params={plainParams(await searchParams)} />;
}
