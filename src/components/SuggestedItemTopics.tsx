"use client";

import { useMemo, useState } from "react";
import type { SuggestionRow } from "@/lib/domain";
import { moveSuggestedItemsAction } from "@/lib/actions";

type TopicOption = { id: string; name: string };

type SuggestionGroup = {
  topicId: string;
  topicName: string;
  itemCount: number;
  suggestions: SuggestionRow[];
  highCount: number;
  meanScore: number;
};

function percent(score: number) {
  return Math.round(score * 100);
}

// Groups items under their best-ranked topic; topics with the most confident matches come first.
function groupByTopSuggestion(suggestions: SuggestionRow[]): SuggestionGroup[] {
  const groups = new Map<string, SuggestionGroup>();
  for (const suggestion of suggestions) {
    const top = suggestion.candidates[0];
    if (!top) continue;
    const group = groups.get(top.topicId) ?? {
      topicId: top.topicId,
      topicName: top.topicName,
      itemCount: top.itemCount,
      suggestions: [],
      highCount: 0,
      meanScore: 0,
    };
    group.suggestions.push(suggestion);
    if (suggestion.confidence === "HIGH") group.highCount += 1;
    groups.set(top.topicId, group);
  }
  for (const group of groups.values()) {
    group.suggestions.sort((a, b) => b.score - a.score);
    group.meanScore = group.suggestions.reduce((sum, s) => sum + s.score, 0) / group.suggestions.length;
  }
  return [...groups.values()].sort((a, b) => b.highCount - a.highCount || b.meanScore - a.meanScore);
}

export function SuggestedItemTopics({
  suggestions,
  topics,
  returnTo,
}: {
  suggestions: SuggestionRow[];
  topics: TopicOption[];
  returnTo: string;
}) {
  // Moved items are hidden right away; the server refresh that follows drops them from `suggestions`.
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);
  // the one row whose "any topic" picker is open - mounting a single <select> instead of one per row
  const [pickerFor, setPickerFor] = useState<string | null>(null);
  // high-confidence matches start checked so a whole group can be confirmed in one click
  const [selected, setSelected] = useState<Set<string>>(
    () => new Set(suggestions.filter((s) => s.confidence === "HIGH").map((s) => s.id)),
  );

  const visible = useMemo(() => suggestions.filter((s) => !hidden.has(s.id)), [suggestions, hidden]);
  const groups = useMemo(() => groupByTopSuggestion(visible), [visible]);

  const counts = { HIGH: 0, MEDIUM: 0, LOW: 0 };
  for (const suggestion of visible) counts[suggestion.confidence] += 1;

  function setChecked(ids: string[], checked: boolean) {
    setSelected((current) => {
      const next = new Set(current);
      for (const id of ids) {
        if (checked) next.add(id);
        else next.delete(id);
      }
      return next;
    });
  }

  function setHiddenIds(ids: string[], isHidden: boolean) {
    setHidden((current) => {
      const next = new Set(current);
      for (const id of ids) {
        if (isHidden) next.add(id);
        else next.delete(id);
      }
      return next;
    });
  }

  async function move(itemIds: string[], topicId: string) {
    if (!itemIds.length) return;
    setError(null);
    setPickerFor(null);
    setHiddenIds(itemIds, true);
    try {
      const result = await moveSuggestedItemsAction(itemIds, topicId, returnTo);
      if (result.error) throw new Error(result.error);
    } catch (err) {
      setHiddenIds(itemIds, false);
      setError(err instanceof Error ? err.message : "Could not move the items");
    }
  }

  return (
    <section className="suggested-merges item-topic-suggestions">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Semantic ranking / Review only</p>
          <h2>Suggested topics for these items</h2>
        </div>
      </div>
      {error ? <p className="error-banner">{error}</p> : null}
      {visible.length ? (
        <>
          <p className="suggestion-summary">
            {visible.length} items · {counts.HIGH} high · {counts.MEDIUM} medium · {counts.LOW} low confidence ·
            grouped under {groups.length} suggested topics. High-confidence matches are pre-selected; nothing moves
            until you confirm.
          </p>
          {groups.map((group) => {
            const ids = group.suggestions.map((s) => s.id);
            const selectedIds = ids.filter((id) => selected.has(id));
            const allSelected = selectedIds.length === ids.length;

            return (
              <details className="suggestion-group" key={group.topicId} open={group.highCount > 0}>
                <summary>
                  <b>{group.topicName}</b>
                  <span className="suggestion-group-meta">
                    {group.suggestions.length} suggested · {group.highCount} high confidence · topic has{" "}
                    {group.itemCount} items
                  </span>
                </summary>
                <ul className="suggestion-list">
                  {group.suggestions.map(({ id, description, type, candidates, score, confidence }) => (
                    <li className="suggestion-row" key={id}>
                      <input
                        type="checkbox"
                        checked={selected.has(id)}
                        onChange={(e) => setChecked([id], e.target.checked)}
                        aria-label="Select item"
                      />
                      <div className="suggestion-body">
                        <p>{description}</p>
                        <div className="suggestion-meta">
                          <span className={`confidence confidence-${confidence.toLowerCase()}`}>
                            <span />
                            {confidence} · {percent(score)}% match
                          </span>
                          <span className="type-label">{type}</span>
                          {candidates.slice(1).map((candidate) => (
                            <button
                              className="candidate-chip"
                              key={candidate.topicId}
                              onClick={() => void move([id], candidate.topicId)}
                              title={`Move this item to "${candidate.topicName}"`}
                            >
                              → {candidate.topicName} ({percent(candidate.score)}%)
                            </button>
                          ))}
                          {pickerFor === id ? (
                            <select
                              autoFocus
                              defaultValue=""
                              onChange={(e) => void move([id], e.target.value)}
                              onBlur={() => setPickerFor(null)}
                              aria-label="Move to another topic"
                            >
                              <option value="" disabled>
                                Choose topic…
                              </option>
                              {topics.map((topic) => (
                                <option key={topic.id} value={topic.id}>
                                  {topic.name}
                                </option>
                              ))}
                            </select>
                          ) : (
                            <button className="candidate-chip" onClick={() => setPickerFor(id)}>
                              Other topic…
                            </button>
                          )}
                        </div>
                      </div>
                    </li>
                  ))}
                </ul>
                <div className="suggestion-group-actions">
                  <label>
                    <input type="checkbox" checked={allSelected} onChange={(e) => setChecked(ids, e.target.checked)} />
                    Select all
                  </label>
                  <button disabled={!selectedIds.length} onClick={() => void move(selectedIds, group.topicId)}>
                    Move {selectedIds.length} selected to &quot;{group.topicName}&quot;
                  </button>
                </div>
              </details>
            );
          })}
        </>
      ) : (
        <p className="empty">No topic suggestions right now.</p>
      )}
    </section>
  );
}
