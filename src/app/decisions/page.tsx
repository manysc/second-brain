import { AppShell } from "@/Presentation/Components/AppShell";
import { KnowledgeCard } from "@/Presentation/Components/KnowledgeCard";
import { useCases } from "@/composition";
export default async function Decisions() { const items = await useCases.listItems("DECISION"); return <AppShell><div className="page-head"><div><p className="eyebrow">Knowledge / Decision journal</p><h1>Why we chose a direction</h1><p className="lede">Decisions are more useful when their rationale and surrounding questions travel with them.</p></div></div><div className="card-grid page-cards">{items.map((item) => <KnowledgeCard key={item.id} item={item} />)}</div></AppShell>; }
