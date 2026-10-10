import { AppShell } from "@/Presentation/Components/AppShell";
import { TopicGrid } from "@/Presentation/Components/TopicGrid";
import { SuggestedTopicMerges } from "@/Presentation/Components/SuggestedTopicMerges";
import { useCases } from "@/composition";
import { createTopicAction } from "@/Presentation/Controllers/topicActions";
import { type TopicPriorityLevel, byPriorityDesc } from "@/Domain";

const PRIORITY_FILTERS: (TopicPriorityLevel | "ALL")[] = ["ALL", "CRITICAL", "MAJOR", "MINOR"];

export default async function Topics({
  searchParams,
}: {
  searchParams: Promise<{ error?: string; priority?: string }>;
}) {
  const [topics, suggestions, params] = await Promise.all([
    useCases.listTopics(),
    useCases.suggestTopicMerges(),
    searchParams,
  ]);
  const error = params.error;
  const activeFilter = (params.priority?.toUpperCase() as TopicPriorityLevel | undefined) ?? null;

  const filteredTopics = activeFilter
    ? topics.filter((t) => (t.priority?.effectivePriority ?? null) === activeFilter)
    : topics;
  const sortedTopics = [...filteredTopics].sort(byPriorityDesc);

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


