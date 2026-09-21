import { deleteItemAction, updateItemAction } from "@/lib/actions";
import type { KnowledgeItem } from "@/lib/domain";

// Items added by hand live on the synthetic "manual" meeting (see backend MANUAL_MEETING_ID).
const MANUAL_MEETING_ID = "manual";

export function EditItemForm({ item, topicId }: { item: KnowledgeItem; topicId: string }) {
  const isManual = item.meetingId === MANUAL_MEETING_ID;

  return (
    <div className="item-manage">
      <details className="note-edit">
        <summary>Edit item</summary>
        <form className="note-form" action={updateItemAction}>
          <input type="hidden" name="itemId" value={item.id} />
          <input type="hidden" name="topicId" value={topicId} />
          {isManual ? (
            <select name="type" defaultValue={item.type} aria-label="Item type">
              <option value="IDEA">Idea</option>
              <option value="QUESTION">Question</option>
              <option value="DECISION">Decision</option>
              <option value="ACTION">Action</option>
            </select>
          ) : null}
          <textarea name="description" rows={3} defaultValue={item.description} required maxLength={2000} />
          <input name="owner" defaultValue={item.owner ?? ""} placeholder="Owner (optional)" maxLength={200} />
          <input name="dueDate" defaultValue={item.dueDate ?? ""} placeholder="Due date (optional)" maxLength={50} />
          <textarea name="rationale" rows={2} defaultValue={item.rationale ?? ""} placeholder="Rationale (optional)" maxLength={2000} />
          <button>Save</button>
        </form>
      </details>
      {isManual ? (
        <details className="note-edit">
          <summary>Delete item</summary>
          <form action={deleteItemAction}>
            <input type="hidden" name="itemId" value={item.id} />
            <input type="hidden" name="topicId" value={topicId} />
            <p>Delete this item and its notes? This cannot be undone.</p>
            <button>Confirm delete</button>
          </form>
        </details>
      ) : null}
    </div>
  );
}
