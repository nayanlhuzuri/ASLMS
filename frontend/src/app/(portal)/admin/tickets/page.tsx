import { STATUSES, TicketsList, type TicketStatus } from "@/components/admin/Tickets";

export default async function Page({ searchParams }: { searchParams: Promise<{ status?: string }> }) {
  const { status } = await searchParams;
  const chosen = (STATUSES as readonly string[]).includes(status ?? "") ? (status as TicketStatus) : "open";
  return <TicketsList key={chosen} status={chosen} />;
}
