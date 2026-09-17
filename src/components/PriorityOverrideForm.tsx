import type { TopicPriorityInfo } from "@/lib/domain";
import { clearPriorityOverrideAction, setPriorityOverrideAction } from "@/lib/actions";

export function PriorityOverrideForm({ topicId, priority }: { topicId: string; priority: TopicPriorityInfo | null }) {
  const override = priority?.manualOverride ?? null;

  if (override) {
    return (
      <div className="priority-override">
        <p className="priority-override-current">
          Manually overridden to <b>{override.priority}</b>
          {override.reason ? ` — ${override.reason}` : ""}
        </p>
        <form action={clearPriorityOverrideAction}>
          <input type="hidden" name="topicId" value={topicId} />
          <button>Clear override</button>
        </form>
      </div>
    );
  }

  return (
    <form className="priority-override-form" action={setPriorityOverrideAction}>
      <input type="hidden" name="topicId" value={topicId} />
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
  );
}
