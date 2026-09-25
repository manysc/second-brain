import Link from "next/link";
import type { KnowledgeItem } from "@/lib/domain";
import { PriorityBadge } from "@/components/PriorityBadge";
import { StatusBadge } from "@/components/StatusBadge";
import { NotesSection } from "@/components/NotesSection";
import { ItemTags } from "@/components/ItemTags";
import { TagChip } from "@/components/TagChip";
import {
  addItemNoteAction,
  clearItemPriorityOverrideAction,
  deleteItemNoteAction,
  setItemPriorityOverrideAction,
  setItemStatusAction,
  updateItemNoteAction,
} from "@/lib/actions";

export function Confidence({ value }: { value: string }) {
  return (
    <span className={`confidence confidence-${value.toLowerCase()}`}>
      <span />
      {value}
    </span>
  );
}

export function KnowledgeCard({ item }: { item: KnowledgeItem }) {
  // Owner is already shown separately, so only surface stakeholders beyond the owner here.
  const otherStakeholders = item.stakeholders.filter((name) => name !== item.owner);
  const priorityInfo = item.effectivePriority
    ? { effectivePriority: item.effectivePriority, manualOverride: item.manualOverride }
    : null;

  return (
    <article className={`knowledge-card item-${item.type.toLowerCase()}`}>
      <div className="card-top">
        <span className="type-label">{item.type}</span>
        <PriorityBadge priority={priorityInfo} />
      </div>
      <h3>{item.description}</h3>
      {item.tags.length ? (
        <div className="topic-tags-list">
          {item.tags.map((tag) => (
            <TagChip key={tag} tag={tag} />
          ))}
        </div>
      ) : null}
      {item.type === "QUESTION" || item.type === "ACTION" ? (
        <div className="card-status">
          <StatusBadge status={item.status} />
          <form action={setItemStatusAction}>
            <input type="hidden" name="itemId" value={item.id} />
            <input type="hidden" name="status" value={item.status === "Open" ? "Closed" : "Open"} />
            <button>{item.status === "Open" ? "Close" : "Reopen"}</button>
          </form>
        </div>
      ) : null}
      <div className="card-meta">
        <span>{item.id}</span>
        {item.topicId ? (
          <Link href={`/topics/${encodeURIComponent(item.topicId)}`}>Topic: {item.topicName}</Link>
        ) : null}
        <span>{item.owner ?? "Owner unassigned"}</span>
        <span>{otherStakeholders.length ? otherStakeholders.join(", ") : "No other stakeholders"}</span>
        {item.dueDate ? <span>Due {item.dueDate}</span> : <span>No due date</span>}
      </div>
      <div className="card-priority">
        {/* this is extraction confidence, not priority - the priority badge moved to card-top above */}
        <span className="item-confidence">
          <small>Confidence</small>
          <Confidence value={item.confidence} />
        </span>
        <details className="item-priority-override">
          <summary>{item.manualOverride ? "Priority override" : "Override priority"}</summary>
          {item.manualOverride ? (
            <div className="priority-override-current-row">
              <p className="priority-override-current">
                Manually overridden to <b>{item.manualOverride.priority}</b>
                {item.manualOverride.reason ? ` — ${item.manualOverride.reason}` : ""}
              </p>
              <form action={clearItemPriorityOverrideAction}>
                <input type="hidden" name="itemId" value={item.id} />
                <button>Clear override</button>
              </form>
            </div>
          ) : (
            <form className="priority-override-form" action={setItemPriorityOverrideAction}>
              <input type="hidden" name="itemId" value={item.id} />
              <select name="priority" defaultValue="" required>
                <option value="" disabled>
                  Set manual priority…
                </option>
                <option value="CRITICAL">Critical</option>
                <option value="MAJOR">Major</option>
                <option value="MINOR">Minor</option>
              </select>
              <input name="reason" placeholder="Reason (optional)" />
              <button>Override</button>
            </form>
          )}
        </details>
      </div>
      <ItemTags itemId={item.id} tags={item.tags} />
      <details className="item-notes">
        <summary>{item.notes.length ? `Notes (${item.notes.length})` : "Add note"}</summary>
        <NotesSection
          notes={item.notes}
          parentField="itemId"
          parentId={item.id}
          addAction={addItemNoteAction}
          editAction={updateItemNoteAction}
          deleteAction={deleteItemNoteAction}
        />
      </details>
      <details className="evidence">
        <summary>Inspect evidence</summary>
        <blockquote>“{item.evidence.quote}”</blockquote>
        <p>{item.evidence.context}</p>
        <small>
          {item.evidence.speaker ?? "Speaker uncertain"} · {item.evidence.timestamp ?? "Timestamp unavailable"}
        </small>
      </details>
    </article>
  );
}
