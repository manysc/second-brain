import Link from "next/link";
import { AppShell } from "@/components/AppShell";
import { KnowledgeCard } from "@/components/KnowledgeCard";
import { TopicAssignmentForm } from "@/components/TopicAssignmentForm";
import { getTopicById, getTopics } from "@/lib/api";
import { deleteTopicAction, updateTopicAction } from "@/lib/actions";

export default async function TopicDetail({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ error?: string }>;
}) {
  const { id } = await params;
  const [topic, topics, error] = await Promise.all([getTopicById(id), getTopics(), (await searchParams).error]);
  const decisions = topic.items.filter((i) => i.type === "DECISION");
  const actions = topic.items.filter((i) => i.type === "ACTION");
  const questions = topic.items.filter((i) => i.type === "QUESTION");

  return (
    <AppShell>
      <div className="page-head compact">
        <div>
          <Link className="back-link" href="/topics">← Topics</Link>
          <p className="eyebrow">Topic intelligence / Active</p>
          <h1>{topic.name}</h1>
          <p className="lede">{topic.items.length} evidence-backed items currently contribute to this thread.</p>
        </div>
        <span className="health-badge">WATCH</span>
      </div>
      {error ? <p className="error-banner">{error}</p> : null}
      <div className="topic-detail-actions">
        <form action={updateTopicAction}>
          <input type="hidden" name="topicId" value={topic.id} />
          <input name="name" defaultValue={topic.name} required />
          <button>Rename</button>
        </form>
        <form action={deleteTopicAction}>
          <input type="hidden" name="topicId" value={topic.id} />
          <button
            disabled={topic.items.length > 0}
            title={topic.items.length > 0 ? "Reassign all items before deleting" : undefined}
          >
            Delete topic
          </button>
        </form>
      </div>
      <section className="topic-situation">
        <p className="eyebrow">Current situation</p>
        <h2>{topic.items[0]?.description ?? "No items assigned yet"}</h2>
        <p>
          Known: this thread connects to {decisions.length} decisions, {actions.length} actions and{" "}
          {questions.length} unresolved questions. Inferred synthesis is intentionally conservative until more
          meetings arrive.
        </p>
        {topic.items[0] ? (
          <details className="evidence">
            <summary>View evidence</summary>
            <blockquote>“{topic.items[0].evidence.quote}”</blockquote>
            <small>
              {topic.items[0].evidence.speaker ?? "Speaker uncertain"} ·{" "}
              {topic.items[0].evidence.timestamp ?? "Timestamp unavailable"}
            </small>
          </details>
        ) : null}
      </section>
      <div className="topic-columns">
        <section>
          <div className="section-heading">
            <div>
              <p className="eyebrow">Open edges</p>
              <h2>Questions</h2>
            </div>
          </div>
          {questions.length ? (
            questions.map((i) => (
              <div key={i.id}>
                <KnowledgeCard item={i} />
                <TopicAssignmentForm item={i} topics={topics} currentTopicId={topic.id} />
              </div>
            ))
          ) : (
            <p className="empty">No unresolved questions recorded.</p>
          )}
        </section>
        <section>
          <div className="section-heading">
            <div>
              <p className="eyebrow">Direction and work</p>
              <h2>Decisions & actions</h2>
            </div>
          </div>
          {[...decisions, ...actions].length ? (
            [...decisions, ...actions].map((i) => (
              <div key={i.id}>
                <KnowledgeCard item={i} />
                <TopicAssignmentForm item={i} topics={topics} currentTopicId={topic.id} />
              </div>
            ))
          ) : (
            <p className="empty">No decisions or actions recorded.</p>
          )}
        </section>
      </div>
    </AppShell>
  );
}

