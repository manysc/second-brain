"use client";

import { useState } from "react";
import type { FormEvent } from "react";
import type { ReviewCandidate } from "@/Domain";
import { decideReviewCandidateAction } from "@/Presentation/Controllers/reviewActions";

type TopicOption = { id: string; name: string };

type Decision = "ACCEPTED" | "REJECTED";

export function ReviewCandidateList({ candidates, topics }: { candidates: ReviewCandidate[]; topics: TopicOption[] }) {
  // Decided candidates are hidden right away; the server refresh that follows drops them from `candidates`.
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);

  function setHiddenId(id: string, isHidden: boolean) {
    setHidden((current) => {
      const next = new Set(current);
      if (isHidden) next.add(id);
      else next.delete(id);
      return next;
    });
  }

  async function decide(candidateId: string, status: Decision, topicId?: string) {
    setError(null);
    setHiddenId(candidateId, true);
    try {
      const result = await decideReviewCandidateAction(candidateId, status, topicId);
      if (result.error) throw new Error(result.error);
    } catch (err) {
      setHiddenId(candidateId, false);
      setError(err instanceof Error ? err.message : "Could not save the decision");
    }
  }

  function onAccept(event: FormEvent<HTMLFormElement>, candidateId: string) {
    event.preventDefault();
    // "" means the reviewer chose Uncategorized
    const topicId = String(new FormData(event.currentTarget).get("topicId") ?? "");
    void decide(candidateId, "ACCEPTED", topicId);
  }

  function onReject(event: FormEvent<HTMLFormElement>, candidateId: string) {
    event.preventDefault();
    void decide(candidateId, "REJECTED");
  }

  return (
    <>
      {error ? <p className="error-banner">{error}</p> : null}
      <section className="review-list page-review">
        {candidates
          .filter((candidate) => !hidden.has(candidate.id))
          .map((candidate) => (
            <article className="review-item" key={candidate.id}>
              <div>
                <div className="card-top">
                  <span className="type-label">{candidate.type}</span>
                  <span className={`confidence confidence-${candidate.confidence.toLowerCase()}`}>
                    <span />
                    {candidate.confidence}
                  </span>
                </div>
                <h3>{candidate.description}</h3>
                <p>{candidate.reason}</p>
                <details className="evidence">
                  <summary>Inspect evidence</summary>
                  <blockquote>“{candidate.evidence.quote}”</blockquote>
                  <p>{candidate.evidence.context}</p>
                  <small>
                    {candidate.evidence.speaker ?? "Speaker uncertain"} ·{" "}
                    {candidate.evidence.timestamp ?? "Timestamp unavailable"}
                  </small>
                </details>
              </div>
              <div className="review-actions">
                <form onSubmit={(e) => onAccept(e, candidate.id)}>
                  <select name="topicId" defaultValue={candidate.suggestedTopicId ?? ""} aria-label="File under topic">
                    <option value="">Uncategorized</option>
                    {topics.map((topic) => (
                      <option key={topic.id} value={topic.id}>
                        {topic.name}
                      </option>
                    ))}
                  </select>
                  <button>Accept</button>
                </form>
                <form onSubmit={(e) => onReject(e, candidate.id)}>
                  <button>Reject</button>
                </form>
              </div>
            </article>
          ))}
      </section>
    </>
  );
}
