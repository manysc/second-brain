import { AppShell } from "@/components/AppShell";
import { KnowledgeCard } from "@/components/KnowledgeCard";
import { StatusFilterRow, parseStatusFilter } from "@/components/StatusBadge";
import { getItems } from "@/lib/api";

export default async function Actions({ searchParams }: { searchParams: Promise<{ status?: string }> }) {
  const filter = parseStatusFilter((await searchParams).status);
  const all = await getItems("ACTION");
  const open = all.filter((item) => item.status === "Open");
  const items = filter === "All" ? all : all.filter((item) => item.status === filter);
  return (
    <AppShell>
      <div className="page-head">
        <div>
          <p className="eyebrow">Knowledge / Actions</p>
          <h1>Commitments across meetings</h1>
          <p className="lede">The work that someone said would happen, with confidence and context intact.</p>
        </div>
      </div>
      <StatusFilterRow
        basePath="/actions"
        active={filter}
        counts={{ Open: open.length, Closed: all.length - open.length, All: all.length }}
      />
      <div className="card-grid page-cards">
        {items.map((item) => (
          <KnowledgeCard key={item.id} item={item} />
        ))}
      </div>
    </AppShell>
  );
}
