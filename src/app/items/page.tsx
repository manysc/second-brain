import { AppShell } from "@/components/AppShell";
import { KnowledgeCard } from "@/components/KnowledgeCard";
import { BulkMoveProvider, SelectableItem } from "@/components/BulkTopicMove";
import { getItems, getTopics } from "@/lib/api";
import type { ItemType, TopicPriorityLevel } from "@/lib/domain";

const PRIORITY_FILTERS: (TopicPriorityLevel | "ALL")[] = ["ALL", "CRITICAL", "MAJOR", "MINOR"];

export default async function Items({
  searchParams,
}: {
  searchParams: Promise<{ type?: string; priority?: string }>;
}) {
  const params = await searchParams;
  const typeFilter = params.type as ItemType | undefined;
  const priorityFilter = (params.priority?.toUpperCase() as TopicPriorityLevel | undefined) || undefined;
  const [items, topics] = await Promise.all([getItems(typeFilter, priorityFilter), getTopics()]);

  return (
    <AppShell>
      <div className="page-head">
        <div>
          <p className="eyebrow">Knowledge / Items</p>
          <h1>Atomic knowledge</h1>
          <p className="lede">Search and scan the facts that make the bigger picture possible.</p>
        </div>
      </div>
      <div className="filter-row">
        <span className="filter active">All {items.length}</span>
        <span className="filter">Ideas 2</span>
        <span className="filter">Decisions 5</span>
        <span className="filter">Actions 10</span>
        <span className="filter">Questions 7</span>
      </div>
      <div className="filter-row">
        {PRIORITY_FILTERS.map((level) => (
          <a
            key={level}
            href={level === "ALL" ? "/items" : `/items?priority=${level}`}
            className={`filter${(priorityFilter ?? "ALL") === level ? " active" : ""}`}
          >
            {level}
          </a>
        ))}
      </div>
      <BulkMoveProvider topics={topics} returnTo="/items">
        <div className="card-grid">
          {items.map((item) => (
            <SelectableItem key={item.id} id={item.id}>
              <KnowledgeCard item={item} />
            </SelectableItem>
          ))}
        </div>
      </BulkMoveProvider>
    </AppShell>
  );
}
