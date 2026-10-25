import { UsersList } from "@/components/admin/Users";
import { plainParams } from "@/lib/params";

type SP = Promise<Record<string, string | string[] | undefined>>;

// design case-workspace-admin, decision 23: `?user=<id>` (or `new`) opens the side panel
export default async function Page({ searchParams }: { searchParams: SP }) {
  return <UsersList params={plainParams(await searchParams)} />;
}
