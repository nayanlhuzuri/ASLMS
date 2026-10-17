import { ReviewList } from "@/components/nextdates/ReviewList";
import { plainParams } from "@/lib/params";

type SP = Promise<Record<string, string | string[] | undefined>>;

export default async function Page({ searchParams }: { searchParams: SP }) {
  return <ReviewList params={plainParams(await searchParams)} />;
}
