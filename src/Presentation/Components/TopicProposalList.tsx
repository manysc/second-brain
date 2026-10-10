"use client";

import { useState } from "react";
import type { TopicProposal } from "@/Domain";
import { acceptTopicProposalAction, rejectTopicProposalAction } from "@/Presentation/Controllers/reviewActions";
import { TopicProposalCard } from "./TopicProposalCard";

type TopicOption = { id: string; name: string };

export function TopicProposalList({ proposals, topics }: { proposals: TopicProposal[]; topics: TopicOption[] }) {
  // Decided proposals are hidden right away; the server refresh that follows drops them from `proposals`.
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);

  function setHiddenName(name: string, isHidden: boolean) {
    setHidden((current) => {
      const next = new Set(current);
      if (isHidden) next.add(name);
      else next.delete(name);
      return next;
    });
  }

  async function decide(name: string, run: () => Promise<{ error?: string }>) {
    setError(null);
    setHiddenName(name, true);
    try {
      const result = await run();
      if (result.error) throw new Error(result.error);
    } catch (err) {
      setHiddenName(name, false);
      setError(err instanceof Error ? err.message : "Could not save the decision");
    }
  }

  const visible = proposals.filter((proposal) => !hidden.has(proposal.name));

  return (
    <>
      {error ? <p className="error-banner">{error}</p> : null}
      {visible.length ? (
        <section className="review-list page-review">
          <h2>Suggested new topics</h2>
          {visible.map((proposal) => (
            <TopicProposalCard
              key={proposal.name}
              proposal={proposal}
              topics={topics}
              onAccept={(topicName, existingTopicId) =>
                void decide(proposal.name, () => acceptTopicProposalAction(proposal.name, topicName, existingTopicId))
              }
              onReject={() => void decide(proposal.name, () => rejectTopicProposalAction(proposal.name))}
            />
          ))}
        </section>
      ) : null}
    </>
  );
}
