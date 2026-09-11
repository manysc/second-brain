"use client";

import { useState } from "react";
import type { ItemTopicSuggestion } from "@/lib/domain";
import { assignItemTopicAction } from "@/lib/actions";

export function SuggestedItemTopics({ suggestions }: { suggestions: ItemTopicSuggestion[] }) {
  const [confirmingKey, setConfirmingKey] = useState<string | null>(null);

  return (
    <section className="suggested-merges">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Semantic overlap / Review only</p>
          <h2>Suggested topics for these items</h2>
        </div>
      </div>
      {suggestions.length ? (
        suggestions.map(({ item, suggestedTopic, similarity }) => {
          const isConfirming = confirmingKey === item.id;

          return (
            <div className="suggested-merge-row" key={item.id}>
              <div>
                {item.description} — <b>{suggestedTopic.name}</b> ({Math.round(similarity * 100)}% similar)
              </div>
              {isConfirming ? (
                <div className="merge-confirm">
                  <span>
                    Move into &quot;{suggestedTopic.name}&quot;?
                  </span>
                  <button
                    onClick={() => {
                      void assignItemTopicAction(item.id, suggestedTopic.id);
                      setConfirmingKey(null);
                    }}
                  >
                    Confirm move
                  </button>
                  <button onClick={() => setConfirmingKey(null)}>Cancel</button>
                </div>
              ) : (
                <button onClick={() => setConfirmingKey(item.id)}>Review move</button>
              )}
            </div>
          );
        })
      ) : (
        <p className="empty">No topic suggestions right now.</p>
      )}
    </section>
  );
}
