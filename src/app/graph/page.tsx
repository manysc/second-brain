import { AppShell } from "@/components/AppShell";
import { GraphView } from "@/components/GraphView";
import { getGraph } from "@/lib/api";

export default async function GraphPage() {
  const graph = await getGraph();
  return (
    <AppShell>
      <div className="page-head">
        <div>
          <p className="eyebrow">Knowledge / Graph</p>
          <h1>How everything connects</h1>
          <p className="lede">
            Every item as a node, every relationship as an edge - evidence-linked, same-topic, and (optionally)
            semantically similar - to surface clusters and links a flat list would hide.
          </p>
        </div>
      </div>
      <GraphView data={graph} />
    </AppShell>
  );
}
