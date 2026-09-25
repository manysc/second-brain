import { TagChip } from "@/components/TagChip";
import { addTopicTagAction, removeTopicTagAction } from "@/lib/actions";

export function TopicTags({ topicId, tags }: { topicId: string; tags: string[] }) {
  return (
    <section className="topic-tags">
      <p className="eyebrow">Tags</p>
      <div className="topic-tags-list">
        {tags.length ? null : <span className="topic-tags-empty">No tags yet</span>}
        {tags.map((tag) => (
          <form key={tag} action={removeTopicTagAction} className="tag-remove-form">
            <input type="hidden" name="topicId" value={topicId} />
            <input type="hidden" name="tag" value={tag} />
            <TagChip tag={tag} />
            <button className="tag-remove" aria-label={`Remove tag ${tag}`} title={`Remove tag ${tag}`}>
              ×
            </button>
          </form>
        ))}
      </div>
      <form action={addTopicTagAction} className="tag-add-form">
        <input type="hidden" name="topicId" value={topicId} />
        <input name="tag" placeholder="Add a tag" maxLength={80} aria-label="New tag" required />
        <button>Add tag</button>
      </form>
    </section>
  );
}
