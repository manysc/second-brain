"use client";

import { useState } from "react";
import Link from "next/link";
import type { Topic } from "@/lib/domain";
import { mergeTopicsAction } from "@/lib/actions";
import { PriorityBadge } from "@/components/PriorityBadge";

// HTML5 drag-and-drop data type used to identify the dragged topic across cards
const DRAG_DATA_TYPE = "text/topic-id";

export function TopicGrid({ topics }: { topics: Topic[] }) {
  const [dragOverId, setDragOverId] = useState<string | null>(null);

  return (
    <div className="topic-grid">
      {topics.map((topic) => {
        const decisions = topic.items.filter((i) => i.type === "DECISION").length;
        const actions = topic.items.filter((i) => i.type === "ACTION").length;
        const questions = topic.items.filter((i) => i.type === "QUESTION").length;
        // only the catch-all bucket is draggable; every other card is a valid merge target
        const isUncategorized = topic.name === "Uncategorized";

        return (
          <Link
            className={`topic-card${dragOverId === topic.id ? " drag-over" : ""}`}
            key={topic.id}
            href={`/topics/${encodeURIComponent(topic.id)}`}
            draggable={isUncategorized}
            onDragStart={
              isUncategorized
                ? (event) => event.dataTransfer.setData(DRAG_DATA_TYPE, topic.id)
                : undefined
            }
            onDragOver={
              isUncategorized ? undefined : (event) => event.preventDefault()
            }
            onDragEnter={
              isUncategorized
                ? undefined
                : (event) => {
                    event.preventDefault();
                    setDragOverId(topic.id);
                  }
            }
            onDragLeave={
              isUncategorized
                ? undefined
                : () => setDragOverId((current) => (current === topic.id ? null : current))
            }
            onDrop={
              isUncategorized
                ? undefined
                : (event) => {
                    event.preventDefault();
                    setDragOverId(null);
                    const sourceId = event.dataTransfer.getData(DRAG_DATA_TYPE);
                    if (sourceId && sourceId !== topic.id) void mergeTopicsAction(sourceId, topic.id);
                  }
            }
          >
            <div className="topic-top">
              <PriorityBadge priority={topic.priority} />
              {isUncategorized ? <span className="drag-hint">Drag onto a topic to merge</span> : null}
            </div>
            <h2>{topic.name}</h2>
            <p>{topic.items[0]?.description ?? "No items yet"}</p>
            <div className="topic-stats">
              <span><b>{topic.items.length}</b> items</span>
              <span><b>{decisions}</b> decisions</span>
              <span><b>{actions}</b> actions</span>
              <span><b>{questions}</b> questions</span>
            </div>
            <p className="topic-stakeholders">{topic.stakeholders.length ? topic.stakeholders.join(", ") : "No stakeholders"}</p>
          </Link>
        );
      })}
    </div>
  );
}
