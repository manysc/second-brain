import { createItemAction } from "@/lib/actions";
import type { ItemType } from "@/lib/domain";

type Props = {
  topicId: string;
  type: ItemType;
  label: string;
};

export function AddItemForm({ topicId, type, label }: Props) {
  return (
    <details className="note-edit add-item">
      <summary>Add {label}</summary>
      <form className="note-form" action={createItemAction}>
        <input type="hidden" name="topicId" value={topicId} />
        <input type="hidden" name="type" value={type} />
        <textarea name="description" rows={2} placeholder={`Describe the ${label}…`} required maxLength={2000} />
        {type === "ACTION" ? (
          <>
            <input name="owner" placeholder="Owner (optional)" maxLength={200} />
            <input name="dueDate" placeholder="Due date (optional)" maxLength={50} />
          </>
        ) : null}
        <button>Add {label}</button>
      </form>
    </details>
  );
}
