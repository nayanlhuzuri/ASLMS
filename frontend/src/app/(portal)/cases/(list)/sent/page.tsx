import { Sent } from "@/components/files/Sent";
import { plainParams } from "@/lib/params";

type SP = Promise<Record<string, string | string[] | undefined>>;

export default async function Page({ searchParams }: { searchParams: SP }) {
  return <Sent params={plainParams(await searchParams)} />;
}
