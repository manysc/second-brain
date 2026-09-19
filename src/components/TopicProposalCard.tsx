import type { Topic, TopicProposal } from "@/lib/domain";
import { acceptTopicProposalAction, rejectTopicProposalAction } from "@/lib/actions";

export function TopicProposalCard({ proposal, topics }: { proposal: TopicProposal; topics: Topic[] }) {
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
        <form className="topic-proposal-form" action={acceptTopicProposalAction} id={formId}>
          <input type="hidden" name="suggestedName" value={proposal.name} />
          <label>
            Create topic as
            <input name="topicName" defaultValue={proposal.name} />
          </label>
          <label>
            or file under existing topic
            <select name="existingTopicId" defaultValue={proposal.suggestedExistingTopicId ?? ""}>
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
        <form action={rejectTopicProposalAction}>
          <input type="hidden" name="suggestedName" value={proposal.name} />
          <button>Reject</button>
        </form>
      </div>
    </article>
  );
}
