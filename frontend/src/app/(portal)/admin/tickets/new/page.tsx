import { NewTicketForm } from "@/components/admin/Tickets";
import { plainParams } from "@/lib/params";

type SP = Promise<Record<string, string | string[] | undefined>>;

// design office-head-picker, decision 9: `?department=&operation=` fill the form
export default async function Page({ searchParams }: { searchParams: SP }) {
  const query = plainParams(await searchParams);
  return <NewTicketForm department={query.department} operation={query.operation} />;
}
