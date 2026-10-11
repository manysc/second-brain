import Link from "next/link";
import { AppShell } from "@/Presentation/Components/AppShell";
import { KnowledgeCard } from "@/Presentation/Components/KnowledgeCard";
import { ReviewCandidateList } from "@/Presentation/Components/ReviewCandidateList";
import { isUncategorized } from "@/Domain";
import { useCases } from "@/composition";

const GROUPS = ["IDEA", "DECISION", "ACTION", "QUESTION"] as const;

const GROUP_HEADINGS: Record<(typeof GROUPS)[number], string> = {
  IDEA: "Ideas in motion",
  DECISION: "Decisions made",
  ACTION: "Commitments",
  QUESTION: "Still unresolved",
};

export default async function MeetingDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const [meeting, topics] = await Promise.all([useCases.getMeeting(id), useCases.listTopics()]);
  const topicOptions = topics.filter((topic) => !isUncategorized(topic)).map(({ id, name }) => ({ id, name }));
  const pending = meeting.reviewCandidates.filter((candidate) => candidate.status === "PENDING");
  const decided = meeting.reviewCandidates.filter((candidate) => candidate.status !== "PENDING");
  return (
    <AppShell>
      <div className="page-head compact">
        <div>
          <Link className="back-link" href="/meetings">
            ← Meetings
          </Link>
          <p className="eyebrow">
            {meeting.id} / {meeting.date}
          </p>
          <h1>{meeting.title}</h1>
          <p className="lede">Source: {meeting.sourceUrl}. Evidence remains attached to every item.</p>
        </div>
      </div>
      <div className="count-row summary-strip">
        {GROUPS.map((type) => (
          <span key={type}>
            <b>{meeting.items.filter((item) => item.type === type).length}</b> {type.toLowerCase()}s
          </span>
        ))}
        <span>
          <b>{pending.length}</b> review candidates
        </span>
      </div>
      {GROUPS.map((type) => (
        <section className="item-section" key={type}>
          <div className="section-heading">
            <div>
              <p className="eyebrow">{type}</p>
              <h2>{GROUP_HEADINGS[type]}</h2>
            </div>
          </div>
          <div className="card-grid">
            {meeting.items
              .filter((item) => item.type === type)
              .map((item) => (
                <KnowledgeCard key={item.id} item={item} />
              ))}
          </div>
        </section>
      ))}
      {pending.length > 0 ? (
        <>
          <section className="item-section">
            <div className="section-heading">
              <div>
                <p className="eyebrow">Human review</p>
                <h2>Review candidates</h2>
              </div>
            </div>
          </section>
          <ReviewCandidateList candidates={pending} topics={topicOptions} />
        </>
      ) : null}
      {decided.length > 0 ? (
        <section className="item-section">
          <div className="section-heading">
            <div>
              <p className="eyebrow">Human review</p>
              <h2>Decided candidates</h2>
            </div>
          </div>
          <div className="review-list">
            {decided.map((candidate) => (
              <article className="review-item" key={candidate.id}>
                <div>
                  <span className="type-label">
                    {candidate.type} · {candidate.status === "ACCEPTED" ? "Accepted" : "Rejected"}
                  </span>
                  <h3>{candidate.description}</h3>
                  <p>{candidate.reason}</p>
                  <details className="evidence">
                    <summary>Inspect evidence</summary>
                    <blockquote>“{candidate.evidence.quote}”</blockquote>
                  </details>
                </div>
              </article>
            ))}
          </div>
        </section>
      ) : null}
    </AppShell>
  );
}
