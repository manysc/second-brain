"use client";

import { createContext, useContext, useState, type ReactNode } from "react";
import type { Topic } from "@/lib/domain";
import { moveItemsTopicAction } from "@/lib/actions";

// sentinel for "no topic chosen yet" in the <select>, distinct from "" (Unassigned)
const NO_CHOICE = "__none__";

type SelectionContextValue = {
  selected: Set<string>;
  toggle: (id: string) => void;
};

const SelectionContext = createContext<SelectionContextValue | null>(null);

export function BulkMoveProvider({
  topics,
  returnTo,
  children,
}: {
  topics: Topic[];
  returnTo: string;
  children: ReactNode;
}) {
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [topicChoice, setTopicChoice] = useState(NO_CHOICE);

  function toggle(id: string) {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function clear() {
    setSelected(new Set());
    setTopicChoice(NO_CHOICE);
  }

  function move() {
    const topicId = topicChoice === "" ? null : topicChoice;
    void moveItemsTopicAction(Array.from(selected), topicId, returnTo);
    clear();
  }

  return (
    <SelectionContext.Provider value={{ selected, toggle }}>
      {children}
      {selected.size > 0 ? (
        <div className="bulk-move-bar">
          <span>{selected.size} selected</span>
          <select value={topicChoice} onChange={(e) => setTopicChoice(e.target.value)}>
            <option value={NO_CHOICE} disabled>
              Choose topic…
            </option>
            <option value="">Unassigned</option>
            {topics.map((topic) => (
              <option key={topic.id} value={topic.id}>
                {topic.name}
              </option>
            ))}
          </select>
          <button disabled={topicChoice === NO_CHOICE} onClick={move}>
            Move
          </button>
          <button onClick={clear}>Cancel</button>
        </div>
      ) : null}
    </SelectionContext.Provider>
  );
}

export function SelectableItem({ id, children }: { id: string; children: ReactNode }) {
  const context = useContext(SelectionContext);
  if (!context) throw new Error("SelectableItem must be used inside a BulkMoveProvider");
  const { selected, toggle } = context;

  return (
    <div className="selectable-item">
      <input type="checkbox" checked={selected.has(id)} onChange={() => toggle(id)} aria-label="Select item" />
      {children}
    </div>
  );
}
