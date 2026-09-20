import Link from "next/link";
import type { RelatedTopic } from "@/lib/domain";

export function RelatedTopics({ topics }: { topics: RelatedTopic[] }) {
  if (!topics.length) return null;

  return (
    <section className="suggested-merges related-topics">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Semantic overlap</p>
          <h2>Related topics</h2>
        </div>
      </div>
      {topics.map((topic) => (
        <div className="suggested-merge-row" key={topic.id}>
          <div>
            <Link href={`/topics/${topic.id}`}>
              <b>{topic.name}</b>
            </Link>{" "}
            ({topic.itemCount} items) — {Math.round(topic.similarity * 100)}% similar
          </div>
        </div>
      ))}
    </section>
  );
}
