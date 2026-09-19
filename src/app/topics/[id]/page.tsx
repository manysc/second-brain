import Link from "next/link";
import { AppShell } from "@/components/AppShell";
import { KnowledgeCard } from "@/components/KnowledgeCard";
import { TopicAssignmentForm } from "@/components/TopicAssignmentForm";
import { BulkMoveProvider, SelectableItem } from "@/components/BulkTopicMove";
import { SuggestedItemTopics } from "@/components/SuggestedItemTopics";
import { PriorityDetailsBadge, PriorityDetailsPanel, PriorityDetailsProvider } from "@/components/PriorityDetails";
import { PriorityOverrideForm } from "@/components/PriorityOverrideForm";
import { getMeetings, getSuggestedItemTopics, getTopicById, getTopics } from "@/lib/api";
import { deleteTopicAction, recalculatePriorityAction, updateTopicAction } from "@/lib/actions";
import type { KnowledgeItem } from "@/lib/domain";

export default async function TopicDetail({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ error?: string }>;
}) {
  const { id } = await params;
  const [topic, topics, meetings, error] = await Promise.all([
    getTopicById(id),
    getTopics(),
    getMeetings(),
    (await searchParams).error,
  ]);
  const suggestions = topic.name === "Uncategorized" ? await getSuggestedItemTopics() : [];
  const meetingDateById = new Map(meetings.map((m) => [m.id, m.date]));
  // Items only carry a meetingId, so recency is derived from the parent meeting's date.
  function sortByMeetingDateDesc(items: KnowledgeItem[]) {
    return [...items].sort((a, b) => {
      const dateA = meetingDateById.get(a.meetingId);
      const dateB = meetingDateById.get(b.meetingId);
      if (!dateA && !dateB) return 0;
      if (!dateA) return 1;
      if (!dateB) return -1;
      return dateB.localeCompare(dateA);
    });
  }
  const ideas = sortByMeetingDateDesc(topic.items.filter((i) => i.type === "IDEA"));
  const decisions = sortByMeetingDateDesc(topic.items.filter((i) => i.type === "DECISION"));
  const actions = sortByMeetingDateDesc(topic.items.filter((i) => i.type === "ACTION"));
  const questions = sortByMeetingDateDesc(topic.items.filter((i) => i.type === "QUESTION"));

  return (
    <AppShell>
      <PriorityDetailsProvider>
      <div className="page-head compact">
        <div>
          <Link className="back-link" href="/topics">← Topics</Link>
          <p className="eyebrow">Topic intelligence / Active</p>
          <h1>{topic.name}</h1>
          <p className="lede">{topic.items.length} evidence-backed items currently contribute to this thread.</p>
        </div>
        <PriorityDetailsBadge priority={topic.priority} />
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
      <PriorityDetailsPanel>
      <section className="priority-section">
        <p className="eyebrow">Priority</p>
        {topic.priority ? (
          <>
            <p className="priority-explanation">{topic.priority.explanation}</p>
            {topic.priority.hardEscalations.length ? (
              <ul className="priority-escalations">
                {topic.priority.hardEscalations.map((escalation) => (
                  <li key={escalation.ruleId}>{escalation.reason}</li>
                ))}
              </ul>
            ) : null}
            <table className="priority-breakdown">
              <tbody>
                {topic.priority.signals.map((signal) => (
                  <tr key={signal.type}>
                    <td>{signal.explanation}</td>
                    <td>
                      {signal.weightedScore} / {signal.maxScore}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {topic.priority.semanticContribution ? (
              <p className="priority-semantic">
                Semantic analysis contribution: {topic.priority.semanticContribution.contribution > 0 ? "+" : ""}
                {topic.priority.semanticContribution.contribution}
                {topic.priority.semanticContribution.disagreement ? " (disagrees with structural signals)" : ""}
              </p>
            ) : null}
          </>
        ) : (
          <p className="empty">Priority has not been calculated yet.</p>
        )}
        <form action={recalculatePriorityAction}>
          <input type="hidden" name="topicId" value={topic.id} />
          <button>Recalculate priority</button>
        </form>
        <PriorityOverrideForm topicId={topic.id} priority={topic.priority} />
      </section>
      </PriorityDetailsPanel>
      {topic.name === "Uncategorized" ? <SuggestedItemTopics suggestions={suggestions} /> : null}
      <section className="topic-situation">
        <p className="eyebrow">Current situation</p>
        <h2>{topic.items[0]?.description ?? "No items assigned yet"}</h2>
        <p>
          Known: this thread connects to {ideas.length} ideas, {decisions.length} decisions, {actions.length} actions
          and {questions.length} unresolved questions. Inferred synthesis is intentionally conservative until more
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
      <BulkMoveProvider topics={topics} returnTo={`/topics/${topic.id}`}>
        <div className="topic-columns">
          <section>
            <div className="section-heading">
              <div>
                <p className="eyebrow">Emerging thinking</p>
                <h2>Ideas</h2>
              </div>
            </div>
            {ideas.length ? (
              ideas.map((i) => (
                <SelectableItem key={i.id} id={i.id}>
                  <KnowledgeCard item={i} />
                  <TopicAssignmentForm item={i} topics={topics} currentTopicId={topic.id} />
                </SelectableItem>
              ))
            ) : (
              <p className="empty">No ideas recorded yet.</p>
            )}
          </section>
          <section>
            <div className="section-heading">
              <div>
                <p className="eyebrow">Open edges</p>
                <h2>Questions</h2>
              </div>
            </div>
            {questions.length ? (
              questions.map((i) => (
                <SelectableItem key={i.id} id={i.id}>
                  <KnowledgeCard item={i} />
                  <TopicAssignmentForm item={i} topics={topics} currentTopicId={topic.id} />
                </SelectableItem>
              ))
            ) : (
              <p className="empty">No unresolved questions recorded.</p>
            )}
          </section>
          <section>
            <div className="section-heading">
              <div>
                <p className="eyebrow">Direction set</p>
                <h2>Decisions</h2>
              </div>
            </div>
            {decisions.length ? (
              decisions.map((i) => (
                <SelectableItem key={i.id} id={i.id}>
                  <KnowledgeCard item={i} />
                  <TopicAssignmentForm item={i} topics={topics} currentTopicId={topic.id} />
                </SelectableItem>
              ))
            ) : (
              <p className="empty">No decisions recorded.</p>
            )}
          </section>
          <section>
            <div className="section-heading">
              <div>
                <p className="eyebrow">Work in motion</p>
                <h2>Actions</h2>
              </div>
            </div>
            {actions.length ? (
              actions.map((i) => (
                <SelectableItem key={i.id} id={i.id}>
                  <KnowledgeCard item={i} />
                  <TopicAssignmentForm item={i} topics={topics} currentTopicId={topic.id} />
                </SelectableItem>
              ))
            ) : (
              <p className="empty">No actions recorded.</p>
            )}
          </section>
        </div>
      </BulkMoveProvider>
      </PriorityDetailsProvider>
    </AppShell>
  );
}

