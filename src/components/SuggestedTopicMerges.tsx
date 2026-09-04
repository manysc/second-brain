"use client";

import { useState } from "react";
import type { TopicMergeSuggestion } from "@/lib/domain";
import { mergeTopicsAction } from "@/lib/actions";

export function SuggestedTopicMerges({ suggestions }: { suggestions: TopicMergeSuggestion[] }) {
  const [confirmingKey, setConfirmingKey] = useState<string | null>(null);

  return (
    <section className="suggested-merges">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Semantic overlap / Review only</p>
          <h2>Suggested merges</h2>
        </div>
      </div>
      {suggestions.length ? (
        suggestions.map(({ topicA, topicB, similarity }) => {
          // merge the smaller topic into the larger one; tie-break by name for a stable direction
          const [source, target] =
            topicA.items.length !== topicB.items.length
              ? topicA.items.length < topicB.items.length
                ? [topicA, topicB]
                : [topicB, topicA]
              : topicA.name.localeCompare(topicB.name) <= 0
                ? [topicA, topicB]
                : [topicB, topicA];
          const key = `${topicA.id}:${topicB.id}`;
          const isConfirming = confirmingKey === key;

          return (
            <div className="suggested-merge-row" key={key}>
              <div>
                <b>{topicA.name}</b> ({topicA.items.length} items) &amp; <b>{topicB.name}</b> (
                {topicB.items.length} items) — {Math.round(similarity * 100)}% similar
              </div>
              {isConfirming ? (
                <div className="merge-confirm">
                  <span>
                    Merge &quot;{source.name}&quot; into &quot;{target.name}&quot;?
                  </span>
                  <button
                    onClick={() => {
                      void mergeTopicsAction(source.id, target.id);
                      setConfirmingKey(null);
                    }}
                  >
                    Confirm merge
                  </button>
                  <button onClick={() => setConfirmingKey(null)}>Cancel</button>
                </div>
              ) : (
                <button onClick={() => setConfirmingKey(key)}>Review merge</button>
              )}
            </div>
          );
        })
      ) : (
        <p className="empty">No merge suggestions right now.</p>
      )}
    </section>
  );
}
