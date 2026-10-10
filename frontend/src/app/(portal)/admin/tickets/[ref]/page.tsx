import { TicketView } from "@/components/admin/Tickets";

// the mail links write a reference's `/` as `-`; the API resolves that form
export default async function Page({ params }: { params: Promise<{ ref: string }> }) {
  const { ref } = await params;
  return <TicketView ticketRef={decodeURIComponent(ref)} />;
}
