import { UsersList } from "@/components/admin/Users";
import { plainParams } from "@/lib/params";

type SP = Promise<Record<string, string | string[] | undefined>>;

// design portal-ui-polish-2, decision 31: the person's User Details modal over the Users list, its filters and the
// modal's tab (`?tab=`) from the query string
export default async function Page({ params, searchParams }: { params: Promise<{ id: string }>; searchParams: SP }) {
  const { id } = await params;
  return <UsersList params={plainParams(await searchParams)} userId={id} />;
}
