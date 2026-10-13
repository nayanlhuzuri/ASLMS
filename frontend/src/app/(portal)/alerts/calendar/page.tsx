import { Calendar } from "@/components/alerts/Calendar";
import { plainParams } from "@/lib/params";

type SP = Promise<Record<string, string | string[] | undefined>>;

export default async function Page({ searchParams }: { searchParams: SP }) {
  return <Calendar params={plainParams(await searchParams)} />;
}
