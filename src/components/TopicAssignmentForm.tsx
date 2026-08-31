import type { KnowledgeItem, Topic } from "@/lib/domain";
import { moveItemTopicAction } from "@/lib/actions";

export function TopicAssignmentForm({ item, topics, currentTopicId }: { item: KnowledgeItem; topics: Topic[]; currentTopicId: string }) {
  return (
    <form className="move-topic-form" action={moveItemTopicAction}>
      <input type="hidden" name="itemId" value={item.id} />
      <input type="hidden" name="currentTopicId" value={currentTopicId} />
      <select name="topicId" defaultValue={currentTopicId}>
        <option value="">Unassigned</option>
        {topics.map((topic) => (
          <option key={topic.id} value={topic.id}>
            {topic.name}
          </option>
        ))}
      </select>
      <button>Move</button>
    </form>
  );
}
