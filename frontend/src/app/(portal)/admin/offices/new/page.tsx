import { Suspense } from "react";

import { NewOfficeForm } from "@/components/admin/Offices";

export default function Page() {
  return (
    <Suspense>
      <NewOfficeForm />
    </Suspense>
  );
}
