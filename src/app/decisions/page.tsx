import { AppShell } from "@/components/AppShell";
import { KnowledgeCard } from "@/components/KnowledgeCard";
import { loadMeeting } from "@/lib/data";
export default function Decisions() { const meeting = loadMeeting(); const items = meeting.items.filter((item) => item.type === "DECISION"); return <AppShell><div className="page-head"><div><p className="eyebrow">Knowledge / Decision journal</p><h1>Why we chose a direction</h1><p className="lede">Decisions are more useful when their rationale and surrounding questions travel with them.</p></div></div><div className="card-grid page-cards">{items.map((item) => <KnowledgeCard key={item.id} item={item} />)}</div></AppShell>; }
