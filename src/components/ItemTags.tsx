import { TagChip } from "@/components/TagChip";
import { addItemTagAction, removeItemTagAction } from "@/lib/actions";
import { MAX_TAG_LENGTH, MAX_TAGS } from "@/lib/domain";

export function ItemTags({ itemId, tags }: { itemId: string; tags: string[] }) {
  return (
    <details className="item-tags">
      <summary>{tags.length ? `Tags (${tags.length})` : "Add tag"}</summary>
      <div className="topic-tags-list">
        {tags.map((tag) => (
          <form key={tag} action={removeItemTagAction} className="tag-remove-form">
            <input type="hidden" name="itemId" value={itemId} />
            <input type="hidden" name="tag" value={tag} />
            <TagChip tag={tag} />
            <button className="tag-remove" aria-label={`Remove tag ${tag}`} title={`Remove tag ${tag}`}>
              ×
            </button>
          </form>
        ))}
      </div>
      {tags.length < MAX_TAGS ? (
        <form action={addItemTagAction} className="tag-add-form">
          <input type="hidden" name="itemId" value={itemId} />
          <input name="tag" placeholder="Add a tag" maxLength={MAX_TAG_LENGTH} aria-label="New tag" required />
          <button>Add tag</button>
        </form>
      ) : (
        <p className="topic-tags-empty">Tag limit reached ({MAX_TAGS})</p>
      )}
    </details>
  );
}
