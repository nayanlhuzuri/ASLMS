import { UserTypePage } from "@/components/admin/UserTypes";

// design case-workspace-admin, decision 25: one user type's functions as plain-language switches
export default async function Page({ params }: { params: Promise<{ role: string }> }) {
  const { role } = await params;
  return <UserTypePage role={decodeURIComponent(role)} />;
}
