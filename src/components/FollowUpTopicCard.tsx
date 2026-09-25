import Link from "next/link";
import type { FollowUpTopic } from "@/lib/domain";
import { PriorityBadge } from "@/components/PriorityBadge";
import { KnowledgeCard } from "@/components/KnowledgeCard";

export function FollowUpTopicCard({ topic }: { topic: FollowUpTopic }) {
  // prefer the concrete "what changed" driver; fall back to the topic's general priority reasoning
  const whyNow = topic.escalatedRecently
    ? topic.escalationDrivers.join("; ") || "Priority increased recently"
    : topic.topic.priority?.explanation ?? null;

  return (
    <section className="briefing-block follow-up-topic">
      <div className="topic-top">
        <PriorityBadge priority={topic.topic.priority} />
      </div>
      <h2>
        <Link href={`/topics/${encodeURIComponent(topic.topic.id)}`}>{topic.topic.name}</Link>
      </h2>
      {whyNow ? <p>{whyNow}</p> : null}
      <details className="follow-up-body">
        <summary>Follow-up items ({topic.followUpItems.length})</summary>
        <div className="card-grid">
          {topic.followUpItems.map((item) => (
            <KnowledgeCard key={item.id} item={item} />
          ))}
        </div>
        {topic.relatedFromOtherTopics.length ? (
          <div className="follow-up-related">
            <p className="eyebrow">Related in other topics</p>
            {topic.relatedFromOtherTopics.map((related) => (
              <div key={related.item.id}>
                <Link href={`/topics/${encodeURIComponent(related.topicId)}`} className="evidence-link">
                  {related.topicName}
                </Link>
                <p>{related.item.description}</p>
              </div>
            ))}
          </div>
        ) : null}
      </details>
    </section>
  );
}
