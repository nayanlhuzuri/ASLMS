/**
 * Ticket list statuses, shared by the server page (`/admin/tickets`) and the client list. Kept out of the
 * `"use client"` component module: a server component that imports a plain value from a client module receives a
 * client reference, not the value (the page then fails with "STATUSES.includes is not a function").
 */
export const STATUSES = ["open", "approved", "rejected", "withdrawn", "all"] as const;
export type TicketStatus = (typeof STATUSES)[number];

/** The `?status=` query value as a known status; anything else is the default list, `open`. */
export function parseStatus(value: string | undefined): TicketStatus {
  return (STATUSES as readonly string[]).includes(value ?? "") ? (value as TicketStatus) : "open";
}
