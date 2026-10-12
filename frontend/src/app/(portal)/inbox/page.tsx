import { InboxIndex } from "@/components/inbox/InboxFrame";
import { plainParams } from "@/lib/params";

type SP = Promise<Record<string, string | string[] | undefined>>;

export default async function Page({ searchParams }: { searchParams: SP }) {
  return <InboxIndex params={plainParams(await searchParams)} />;
}
