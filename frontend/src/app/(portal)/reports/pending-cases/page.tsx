import { ReportPage } from "@/components/reports/ReportPage";
import { plainParams } from "@/lib/params";

type SP = Promise<Record<string, string | string[] | undefined>>;

export default async function Page({ searchParams }: { searchParams: SP }) {
  return <ReportPage reportKey="pending-cases" params={plainParams(await searchParams)} />;
}
