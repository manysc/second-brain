import { AppShell } from "@/Presentation/Components/AppShell";
import { KnowledgeCard } from "@/Presentation/Components/KnowledgeCard";
import { StatusFilterRow, parseStatusFilter } from "@/Presentation/Components/StatusBadge";
import { useCases } from "@/composition";

export default async function Questions({ searchParams }: { searchParams: Promise<{ status?: string }> }) {
  const filter = parseStatusFilter((await searchParams).status);
  const all = await useCases.listItems("QUESTION");
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
