import { NewUserForm } from "@/components/admin/Users";
import { plainParams } from "@/lib/params";

type SP = Promise<Record<string, string | string[] | undefined>>;

// design office-head-picker, decision 8: `?no_office=1` starts No Office Yet ticked, `?return=` is where to go back
// with `?head=<id>` (New Office or the Reactivate dialog)
export default async function Page({ searchParams }: { searchParams: SP }) {
  const query = plainParams(await searchParams);
  return <NewUserForm noOffice={query.no_office === "1"} returnTo={query.return} />;
}
