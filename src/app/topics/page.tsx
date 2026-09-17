import { AppShell } from "@/components/AppShell";
import { TopicGrid } from "@/components/TopicGrid";
import { SuggestedTopicMerges } from "@/components/SuggestedTopicMerges";
import { getSuggestedTopicMerges, getTopics } from "@/lib/api";
import { createTopicAction } from "@/lib/actions";
import { PRIORITY_RANK, type TopicPriorityLevel } from "@/lib/domain";

const PRIORITY_FILTERS: (TopicPriorityLevel | "ALL")[] = ["ALL", "CRITICAL", "MAJOR", "MINOR"];

export default async function Topics({
  searchParams,
}: {
  searchParams: Promise<{ error?: string; priority?: string }>;
}) {
  const [topics, suggestions, params] = await Promise.all([
    getTopics(),
    getSuggestedTopicMerges(),
    searchParams,
  ]);
  const error = params.error;
  const activeFilter = (params.priority?.toUpperCase() as TopicPriorityLevel | undefined) ?? null;

  const filteredTopics = activeFilter
    ? topics.filter((t) => (t.priority?.effectivePriority ?? null) === activeFilter)
    : topics;
  // highest priority first, then by score within the same priority level
  const sortedTopics = [...filteredTopics].sort((a, b) => {
    const rankA = a.priority ? PRIORITY_RANK[a.priority.effectivePriority] : -1;
    const rankB = b.priority ? PRIORITY_RANK[b.priority.effectivePriority] : -1;
    if (rankA !== rankB) return rankB - rankA;
    return (b.priority?.calculatedScore ?? 0) - (a.priority?.calculatedScore ?? 0);
  });

  return (
    <AppShell>
      <div className="page-head">
        <div>
          <p className="eyebrow">Knowledge / Topics</p>
          <h1>Persistent threads</h1>
          <p className="lede">A topic is a living body of knowledge, not a label. Start with what the meeting made visible.</p>
        </div>
      </div>
      {error ? <p className="error-banner">{error}</p> : null}
      <div className="filter-row">
        {PRIORITY_FILTERS.map((level) => (
          <a
            key={level}
            href={level === "ALL" ? "/topics" : `/topics?priority=${level}`}
            className={`filter${(activeFilter ?? "ALL") === level ? " active" : ""}`}
          >
            {level === "ALL" ? `All ${topics.length}` : level}
          </a>
        ))}
      </div>
      <form className="topic-toolbar" action={createTopicAction}>
        <input name="name" placeholder="New topic name" required />
        <button>Create topic</button>
      </form>
      <SuggestedTopicMerges suggestions={suggestions} />
      <TopicGrid topics={sortedTopics} />
    </AppShell>
  );
}


