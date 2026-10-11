import Link from "next/link";
import { plural } from "@/Presentation/format";

/** Says how many items the age cut-off left out of the briefing; nothing when it hid none or was off. */
export function StaleItemsNote({
  count,
  days,
  showAllHref,
}: {
  count: number;
  days: number | null;
  showAllHref: string;
}) {
  if (!count || days === null) return null;
  return (
    <p className="briefing-note">
      {plural(count, "item")} with no activity in {days} days {count === 1 ? "is" : "are"} hidden.{" "}
      <Link href={showAllHref}>Show {count === 1 ? "it" : "them"}</Link>
    </p>
  );
}
