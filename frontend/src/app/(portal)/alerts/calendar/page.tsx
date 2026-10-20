import { CalendarRedirect } from "@/components/calendar/CalendarRedirect";
import { plainParams } from "@/lib/params";

type SP = Promise<Record<string, string | string[] | undefined>>;

// design portal-ui-redesign, decision 8: the hearing calendar moved to My calendar; old links land there
export default async function Page({ searchParams }: { searchParams: SP }) {
  return <CalendarRedirect params={plainParams(await searchParams)} />;
}
