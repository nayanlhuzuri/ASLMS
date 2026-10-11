import { TicketsList } from "@/components/admin/Tickets";
import { parseStatus } from "@/lib/tickets";

export default async function Page({ searchParams }: { searchParams: Promise<{ status?: string }> }) {
  const { status } = await searchParams;
  const chosen = parseStatus(status);
  return <TicketsList key={chosen} status={chosen} />;
}
