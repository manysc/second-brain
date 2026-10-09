"use client";

import { useMemo, useState } from "react";
import type { Confidence, SuggestionRow } from "@/lib/domain";
import { createTopicAndMoveItemsAction, moveSuggestedItemsAction } from "@/lib/actions";

type TopicOption = { id: string; name: string };

type Move = { itemIds: string[]; topicId: string };

// the last confirmed batch, kept so it can be sent back to Uncategorized in one click
type LastMove = { itemIds: string[]; topicCount: number };

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

function plural(count: number, word: string) {
  return `${count} ${word}${count === 1 ? "" : "s"}`;
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

// Inline name field for filing items into a topic that doesn't exist yet; closes when left empty.
function NewTopicForm({ onSubmit, onCancel }: { onSubmit: (name: string) => void; onCancel: () => void }) {
  const [name, setName] = useState("");

  return (
    <form
      className="new-topic-form"
      onSubmit={(e) => {
        e.preventDefault();
        if (name.trim()) onSubmit(name.trim());
      }}
      onBlur={(e) => {
        if (!name.trim() && !e.currentTarget.contains(e.relatedTarget)) onCancel();
      }}
    >
      <input
        autoFocus
        required
        value={name}
        onChange={(e) => setName(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Escape") onCancel();
        }}
        placeholder="New topic name"
        aria-label="New topic name"
      />
      <button type="submit">Create</button>
      <button type="button" className="new-topic-cancel" onClick={onCancel} aria-label="Cancel">
        ×
      </button>
    </form>
  );
}

export function SuggestedItemTopics({
  suggestions,
  topics,
  returnTo,
  uncategorizedTopicId,
}: {
  suggestions: SuggestionRow[];
  topics: TopicOption[];
  returnTo: string;
  uncategorizedTopicId: string;
}) {
  // Moved items are hidden right away; the server refresh that follows drops them from `suggestions`.
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const [lastMove, setLastMove] = useState<LastMove | null>(null);
  // the one row whose "any topic" picker is open - mounting a single <select> instead of one per row
  const [pickerFor, setPickerFor] = useState<string | null>(null);
  // the one open "new topic" field: an item id, or `group:<topicId>` for a group's selected rows
  const [newTopicFor, setNewTopicFor] = useState<string | null>(null);
  // high-confidence matches start checked so a whole group can be confirmed in one click
  const [selected, setSelected] = useState<Set<string>>(
    () => new Set(suggestions.filter((s) => s.confidence === "HIGH").map((s) => s.id)),
  );

  const visible = useMemo(() => suggestions.filter((s) => !hidden.has(s.id)), [suggestions, hidden]);
  const groups = useMemo(() => groupByTopSuggestion(visible), [visible]);

  const counts = { HIGH: 0, MEDIUM: 0, LOW: 0 };
  for (const suggestion of visible) counts[suggestion.confidence] += 1;

  // every group's checked rows, each bound for that group's topic - what "File all" confirms
  const plannedMoves: Move[] = groups
    .map((group) => ({
      topicId: group.topicId,
      itemIds: group.suggestions.filter((s) => selected.has(s.id)).map((s) => s.id),
    }))
    .filter((m) => m.itemIds.length);
  const plannedCount = plannedMoves.reduce((sum, m) => sum + m.itemIds.length, 0);

  function selectBands(bands: Confidence[]) {
    setSelected(new Set(visible.filter((s) => bands.includes(s.confidence)).map((s) => s.id)));
  }

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

  async function move(moves: Move[]) {
    const batch = moves.filter((m) => m.itemIds.length);
    if (!batch.length) return;
    const itemIds = batch.flatMap((m) => m.itemIds);
    setError(null);
    setPickerFor(null);
    setNewTopicFor(null);
    setLastMove(null);
    setHiddenIds(itemIds, true);
    try {
      const result = await moveSuggestedItemsAction(batch, returnTo);
      const failed = new Set(result.failedItemIds ?? []);
      if (failed.size) setHiddenIds([...failed], false);
      if (result.error) setError(result.error);
      const moved = batch.filter((m) => m.itemIds.some((id) => !failed.has(id)));
      if (moved.length) {
        setLastMove({
          itemIds: itemIds.filter((id) => !failed.has(id)),
          topicCount: new Set(moved.map((m) => m.topicId)).size,
        });
      }
    } catch (err) {
      setHiddenIds(itemIds, false);
      setError(err instanceof Error ? err.message : "Could not move the items");
    }
  }

  // Files items into a topic created on the spot; a name that already exists reuses that topic.
  async function moveToNewTopic(name: string, itemIds: string[]) {
    if (!itemIds.length) return;
    const existing = topics.find((t) => t.name.trim().toLowerCase() === name.toLowerCase());
    if (existing) return move([{ itemIds, topicId: existing.id }]);

    setError(null);
    setPickerFor(null);
    setNewTopicFor(null);
    setLastMove(null);
    setHiddenIds(itemIds, true);
    try {
      const result = await createTopicAndMoveItemsAction(name, itemIds, returnTo);
      if (result.error) throw new Error(result.error);
      setLastMove({ itemIds, topicCount: 1 });
    } catch (err) {
      setHiddenIds(itemIds, false);
      setError(err instanceof Error ? err.message : "Could not create the topic");
    }
  }

  // Sends the last batch back to Uncategorized; the server refresh then returns the rows to the
  // panel, still checked, so the wrong ones can be unticked and the rest re-filed.
  async function undo() {
    if (!lastMove) return;
    const previous = lastMove;
    setError(null);
    setLastMove(null);
    try {
      const result = await moveSuggestedItemsAction(
        [{ itemIds: previous.itemIds, topicId: uncategorizedTopicId }],
        returnTo,
      );
      if (result.error) throw new Error(result.error);
      setHiddenIds(previous.itemIds, false);
    } catch (err) {
      setLastMove(previous);
      setError(err instanceof Error ? err.message : "Could not undo the move");
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
      {lastMove ? (
        <p className="undo-bar" role="status">
          <span>
            Filed {plural(lastMove.itemIds.length, "item")} into {plural(lastMove.topicCount, "topic")}.
          </span>
          <button className="undo-button" onClick={() => void undo()}>
            Undo
          </button>
          <button className="undo-dismiss" onClick={() => setLastMove(null)} aria-label="Dismiss">
            ×
          </button>
        </p>
      ) : null}
      {visible.length ? (
        <>
          <p className="suggestion-summary">
            {visible.length} items · {counts.HIGH} high · {counts.MEDIUM} medium · {counts.LOW} low confidence ·
            grouped under {groups.length} suggested topics. High-confidence matches are pre-selected; nothing moves
            until you confirm, and every move can be undone.
          </p>
          <div className="suggestion-toolbar">
            <span className="suggestion-presets">
              Select
              <button onClick={() => selectBands(["HIGH"])}>High</button>
              <button onClick={() => selectBands(["HIGH", "MEDIUM"])}>High + medium</button>
              <button onClick={() => selectBands([])}>None</button>
            </span>
            <button className="suggestion-file-all" disabled={!plannedCount} onClick={() => void move(plannedMoves)}>
              File {plannedCount} selected into {plural(plannedMoves.length, "topic")}
            </button>
          </div>
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
                              onClick={() => void move([{ itemIds: [id], topicId: candidate.topicId }])}
                              title={`Move this item to "${candidate.topicName}"`}
                            >
                              → {candidate.topicName} ({percent(candidate.score)}%)
                            </button>
                          ))}
                          {pickerFor === id ? (
                            <select
                              autoFocus
                              defaultValue=""
                              onChange={(e) => void move([{ itemIds: [id], topicId: e.target.value }])}
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
                            <button
                              className="candidate-chip"
                              onClick={() => {
                                setNewTopicFor(null);
                                setPickerFor(id);
                              }}
                            >
                              Other topic…
                            </button>
                          )}
                          {newTopicFor === id ? (
                            <NewTopicForm
                              onSubmit={(name) => void moveToNewTopic(name, [id])}
                              onCancel={() => setNewTopicFor(null)}
                            />
                          ) : (
                            <button
                              className="candidate-chip"
                              onClick={() => {
                                setPickerFor(null);
                                setNewTopicFor(id);
                              }}
                            >
                              + New topic…
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
                  <span className="suggestion-group-moves">
                    {newTopicFor === `group:${group.topicId}` ? (
                      <NewTopicForm
                        onSubmit={(name) => void moveToNewTopic(name, selectedIds)}
                        onCancel={() => setNewTopicFor(null)}
                      />
                    ) : (
                      <button
                        className="suggestion-new-topic"
                        disabled={!selectedIds.length}
                        onClick={() => {
                          setPickerFor(null);
                          setNewTopicFor(`group:${group.topicId}`);
                        }}
                      >
                        Move {selectedIds.length} selected to new topic…
                      </button>
                    )}
                    <button disabled={!selectedIds.length} onClick={() => void move([{ itemIds: selectedIds, topicId: group.topicId }])}>
                      Move {selectedIds.length} selected to &quot;{group.topicName}&quot;
                    </button>
                  </span>
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
