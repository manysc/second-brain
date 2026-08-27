import type { KnowledgeItem } from "@/lib/domain";
export function Confidence({ value }: { value: string }) { return <span className={`confidence confidence-${value.toLowerCase()}`}><span />{value}</span>; }
export function KnowledgeCard({ item }: { item: KnowledgeItem }) {
  // Owner is already shown separately, so only surface stakeholders beyond the owner here.
  const otherStakeholders = item.stakeholders.filter((name) => name !== item.owner);
  return <article className={`knowledge-card item-${item.type.toLowerCase()}`}><div className="card-top"><span className="type-label">{item.type}</span><Confidence value={item.confidence} /></div><h3>{item.description}</h3><div className="card-meta"><span>{item.id.split(":")[1]}</span><span>{item.owner ?? "Owner unassigned"}</span><span>{otherStakeholders.length ? otherStakeholders.join(", ") : "No other stakeholders"}</span>{item.dueDate ? <span>Due {item.dueDate}</span> : <span>No due date</span>}</div><details className="evidence"><summary>Inspect evidence</summary><blockquote>“{item.evidence.quote}”</blockquote><p>{item.evidence.context}</p><small>{item.evidence.speaker ?? "Speaker uncertain"} · {item.evidence.timestamp ?? "Timestamp unavailable"}</small></details></article>;
}
