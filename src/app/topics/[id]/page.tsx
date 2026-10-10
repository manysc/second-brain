import Link from "next/link";
import { AppShell } from "@/Presentation/Components/AppShell";
import { KnowledgeCard } from "@/Presentation/Components/KnowledgeCard";
import { TopicAssignmentForm } from "@/Presentation/Components/TopicAssignmentForm";
import { BulkMoveProvider, SelectableItem } from "@/Presentation/Components/BulkTopicMove";
import { SuggestedItemTopics } from "@/Presentation/Components/SuggestedItemTopics";
import { PriorityDetailsBadge, PriorityDetailsPanel, PriorityDetailsProvider } from "@/Presentation/Components/PriorityDetails";
import { PriorityOverrideForm } from "@/Presentation/Components/PriorityOverrideForm";
import { RelatedTopics } from "@/Presentation/Components/RelatedTopics";
import { useCases } from "@/composition";
import { NotesSection } from "@/Presentation/Components/NotesSection";
import { TopicImages } from "@/Presentation/Components/TopicImages";
import { TopicTags } from "@/Presentation/Components/TopicTags";
import { AddItemForm } from "@/Presentation/Components/AddItemForm";
import { EditItemForm } from "@/Presentation/Components/EditItemForm";
import { addTopicImageAction, addTopicNoteAction, deleteTopicAction, deleteTopicImageAction, deleteTopicNoteAction, recalculatePriorityAction, setTopicStatusAction, updateTopicAction, updateTopicNoteAction } from "@/Presentation/Controllers/topicActions";
import { orNotFound } from "@/Presentation/pageSupport";
import { type KnowledgeItem, canDeleteTopic, isUncategorized, sortByMeetingDateDesc } from "@/Domain";

const DEFAULT_UNCATEGORIZED_LIMIT = 25;
const SHOW_MORE_STEP = 50;

export default async function TopicDetail({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ error?: string; limit?: string }>;
}) {
  const { id } = await params;
  const { error, limit: rawLimit } = await searchParams;
  const [topic, topics, meetings, relatedTopics] = await Promise.all([
    orNotFound(useCases.getTopic(id)),
    useCases.listTopics(),
    useCases.listMeetings(),
    useCases.listRelatedTopics(id),
  ]);
  const uncategorized = isUncategorized(topic);
  const suggestions = uncategorized ? await useCases.suggestItemTopics() : [];
  const meetingDateById = new Map(meetings.map((m) => [m.id, m.date]));
  const newestFirst = (type: KnowledgeItem["type"]) =>
    sortByMeetingDateDesc(topic.items.filter((i) => i.type === type), meetingDateById);
  const ideas = newestFirst("IDEA");
  const decisions = newestFirst("DECISION");
  const actions = newestFirst("ACTION");
  const questions = newestFirst("QUESTION");
  // Uncategorized can hold hundreds of items; each card carries forms and a topic picker, so only the
  // first `limit` per column are rendered (the suggestions panel above is the main way to triage them).
  const parsedLimit = Number.parseInt(rawLimit ?? "", 10);
  const limit = Number.isFinite(parsedLimit) && parsedLimit > 0 ? parsedLimit : DEFAULT_UNCATEGORIZED_LIMIT;
  function shown(items: KnowledgeItem[]) {
    return uncategorized ? items.slice(0, limit) : items;
  }
  function showMore(total: number) {
    if (!uncategorized || total <= limit) return null;
    return (
      <p className="show-more">
        Showing {limit} of {total} · <Link href={`/topics/${topic.id}?limit=${limit + SHOW_MORE_STEP}`}>Show more</Link>
      </p>
    );
  }

  return (
    <AppShell>
      <PriorityDetailsProvider>
      <div className="page-head compact">
        <div>
          <Link className="back-link" href="/topics">← Topics</Link>
          <p className="eyebrow">Topic intelligence / {topic.status === "Open" ? "Active" : "Closed"}</p>
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
        <form action={setTopicStatusAction}>
          <input type="hidden" name="topicId" value={topic.id} />
          <input type="hidden" name="status" value={topic.status === "Open" ? "Closed" : "Open"} />
          <button>{topic.status === "Open" ? "Close topic" : "Reopen topic"}</button>
        </form>
        <form action={deleteTopicAction}>
          <input type="hidden" name="topicId" value={topic.id} />
          <button
            disabled={!canDeleteTopic(topic)}
            title={canDeleteTopic(topic) ? undefined : "Reassign all items before deleting"}
          >
            Delete topic
          </button>
        </form>
      </div>
      <TopicTags topicId={topic.id} tags={topic.tags} />
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
      <section className="priority-section topic-notes">
        <p className="eyebrow">Notes{topic.notes.length ? ` (${topic.notes.length})` : ""}</p>
        <NotesSection
          notes={topic.notes}
          parentField="topicId"
          parentId={topic.id}
          addAction={addTopicNoteAction}
          editAction={updateTopicNoteAction}
          deleteAction={deleteTopicNoteAction}
        />
      </section>
      <section className="priority-section topic-images">
        <p className="eyebrow">Images{topic.images.length ? ` (${topic.images.length})` : ""}</p>
        <TopicImages
          topicId={topic.id}
          images={topic.images}
          addAction={addTopicImageAction}
          deleteAction={deleteTopicImageAction}
        />
      </section>
      {uncategorized ? (
        <SuggestedItemTopics
          suggestions={suggestions}
          topics={topics
            .filter((t) => !isUncategorized(t))
            .map(({ id, name }) => ({ id, name }))
            .sort((a, b) => a.name.localeCompare(b.name))}
          returnTo={`/topics/${topic.id}`}
          uncategorizedTopicId={topic.id}
        />
      ) : null}
      <RelatedTopics topics={relatedTopics} />
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
            <AddItemForm topicId={topic.id} type="IDEA" label="idea" />
            {ideas.length ? (
              shown(ideas).map((i) => (
                <SelectableItem key={i.id} id={i.id}>
                  <KnowledgeCard item={i} />
                  <TopicAssignmentForm item={i} topics={topics} currentTopicId={topic.id} />
                  <EditItemForm item={i} topicId={topic.id} />
                </SelectableItem>
              ))
            ) : (
              <p className="empty">No ideas recorded yet.</p>
            )}
            {showMore(ideas.length)}
          </section>
          <section>
            <div className="section-heading">
              <div>
                <p className="eyebrow">Open edges</p>
                <h2>Questions</h2>
              </div>
            </div>
            <AddItemForm topicId={topic.id} type="QUESTION" label="question" />
            {questions.length ? (
              shown(questions).map((i) => (
                <SelectableItem key={i.id} id={i.id}>
                  <KnowledgeCard item={i} />
                  <TopicAssignmentForm item={i} topics={topics} currentTopicId={topic.id} />
                  <EditItemForm item={i} topicId={topic.id} />
                </SelectableItem>
              ))
            ) : (
              <p className="empty">No unresolved questions recorded.</p>
            )}
            {showMore(questions.length)}
          </section>
          <section>
            <div className="section-heading">
              <div>
                <p className="eyebrow">Direction set</p>
                <h2>Decisions</h2>
              </div>
            </div>
            <AddItemForm topicId={topic.id} type="DECISION" label="decision" />
            {decisions.length ? (
              shown(decisions).map((i) => (
                <SelectableItem key={i.id} id={i.id}>
                  <KnowledgeCard item={i} />
                  <TopicAssignmentForm item={i} topics={topics} currentTopicId={topic.id} />
                  <EditItemForm item={i} topicId={topic.id} />
                </SelectableItem>
              ))
            ) : (
              <p className="empty">No decisions recorded.</p>
            )}
            {showMore(decisions.length)}
          </section>
          <section>
            <div className="section-heading">
              <div>
                <p className="eyebrow">Work in motion</p>
                <h2>Actions</h2>
              </div>
            </div>
            <AddItemForm topicId={topic.id} type="ACTION" label="action" />
            {actions.length ? (
              shown(actions).map((i) => (
                <SelectableItem key={i.id} id={i.id}>
                  <KnowledgeCard item={i} />
                  <TopicAssignmentForm item={i} topics={topics} currentTopicId={topic.id} />
                  <EditItemForm item={i} topicId={topic.id} />
                </SelectableItem>
              ))
            ) : (
              <p className="empty">No actions recorded.</p>
            )}
            {showMore(actions.length)}
          </section>
        </div>
      </BulkMoveProvider>
      </PriorityDetailsProvider>
    </AppShell>
  );
}

