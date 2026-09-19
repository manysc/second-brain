import type { OpenClosed } from "@/lib/domain";

export function StatusBadge({ status }: { status: OpenClosed }) {
  return <span className={`status-badge status-${status.toLowerCase()}`}>{status}</span>;
}

export const STATUS_FILTERS = ["Open", "Closed", "All"] as const;
export type StatusFilterValue = (typeof STATUS_FILTERS)[number];

// Reads ?status= (defaults to Open); pass the raw search param.
export function parseStatusFilter(raw: string | undefined): StatusFilterValue {
  return STATUS_FILTERS.find((value) => value.toLowerCase() === raw?.toLowerCase()) ?? "Open";
}

export function StatusFilterRow({
  basePath,
  active,
  counts,
}: {
  basePath: string;
  active: StatusFilterValue;
  counts: Record<StatusFilterValue, number>;
}) {
  return (
    <div className="filter-row">
      {STATUS_FILTERS.map((value) => (
        <a
          key={value}
          href={value === "Open" ? basePath : `${basePath}?status=${value.toLowerCase()}`}
          className={`filter${active === value ? " active" : ""}`}
        >
          {value} {counts[value]}
        </a>
      ))}
    </div>
  );
}
