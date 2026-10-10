"use client";

import type { TopicProposal } from "@/Domain";

type TopicOption = { id: string; name: string };

export function TopicProposalCard({
  proposal,
  topics,
  onAccept,
  onReject,
}: {
  proposal: TopicProposal;
  topics: TopicOption[];
  onAccept: (topicName: string | null, existingTopicId: string | null) => void;
  onReject: () => void;
}) {
  const formId = `accept-${encodeURIComponent(proposal.name)}`;
  return (
    <article className="review-item topic-proposal">
      <div>
        <div className="card-top">
          <span className="type-label">New topic</span>
          <span>{proposal.items.length} item{proposal.items.length === 1 ? "" : "s"}</span>
        </div>
        <h3>{proposal.name}</h3>
        <ul>
          {proposal.items.slice(0, 3).map((item) => (
            <li key={item.id}>{item.description}</li>
          ))}
          {proposal.items.length > 3 ? <li>…and {proposal.items.length - 3} more</li> : null}
        </ul>
        <form
          className="topic-proposal-form"
          id={formId}
          onSubmit={(e) => {
            e.preventDefault();
            const form = new FormData(e.currentTarget);
            const topicName = String(form.get("topicName") ?? "").trim();
            const existingTopicId = String(form.get("existingTopicId") ?? "");
            onAccept(topicName || null, existingTopicId || null);
          }}
        >
          <label>
            Create topic as
            <input name="topicName" defaultValue={proposal.name} />
          </label>
          <label>
            or file under existing topic
            {/* picking a topic files the proposal right away; Accept is for the pre-selected or a new topic */}
            <select
              name="existingTopicId"
              defaultValue={proposal.suggestedExistingTopicId ?? ""}
              onChange={(e) => {
                if (e.target.value) onAccept(null, e.target.value);
              }}
            >
              <option value="">— create new topic —</option>
              {topics.map((topic) => (
                <option key={topic.id} value={topic.id}>
                  {topic.name}
                </option>
              ))}
            </select>
          </label>
        </form>
      </div>
      <div className="review-actions">
        <button form={formId}>Accept</button>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            onReject();
          }}
        >
          <button>Reject</button>
        </form>
      </div>
    </article>
  );
}
