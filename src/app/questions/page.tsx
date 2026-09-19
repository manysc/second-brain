import { AppShell } from "@/components/AppShell";
import { KnowledgeCard } from "@/components/KnowledgeCard";
import { StatusFilterRow, parseStatusFilter } from "@/components/StatusBadge";
import { getItems } from "@/lib/api";

export default async function Questions({ searchParams }: { searchParams: Promise<{ status?: string }> }) {
  const filter = parseStatusFilter((await searchParams).status);
  const all = await getItems("QUESTION");
  const open = all.filter((item) => item.status === "Open");
  const items = filter === "All" ? all : all.filter((item) => item.status === filter);
  return (
    <AppShell>
      <div className="page-head">
        <div>
          <p className="eyebrow">Knowledge / Questions</p>
          <h1>Questions worth carrying forward</h1>
          <p className="lede">Unresolved does not mean forgotten. These are the open edges of the work.</p>
        </div>
      </div>
      <StatusFilterRow
        basePath="/questions"
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
