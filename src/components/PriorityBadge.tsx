import type { TopicPriorityInfo } from "@/lib/domain";

const LABELS: Record<string, string> = { CRITICAL: "Critical", MAJOR: "Major", MINOR: "Minor" };

export function PriorityBadge({ priority }: { priority: TopicPriorityInfo | null }) {
  if (!priority) {
    return <span className="priority-badge priority-unknown">Not yet calculated</span>;
  }
  const level = priority.effectivePriority;
  return (
    <span className={`priority-badge priority-${level.toLowerCase()}`}>
      {LABELS[level] ?? level}
      <small>
        {" "}
        · {Math.round(priority.calculatedScore)}/100 · {priority.confidence.toLowerCase()} confidence
      </small>
      {/* effectivePriority can differ from the automatically calculated one when overridden */}
      {priority.manualOverride ? <small className="priority-override-flag"> · manual override</small> : null}
    </span>
  );
}
