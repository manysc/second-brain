"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import type { ForwardRefExoticComponent, RefAttributes } from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { ForceGraphMethods, ForceGraphProps } from "react-force-graph-2d";
import type { GraphData, GraphEdge, GraphNode, ItemType } from "@/lib/domain";

// react-force-graph's default export is a generic component; next/dynamic can't infer that
// generic, so we re-assert the concrete instantiation we actually use.
type GraphLink = { kind: GraphEdge["kind"]; weight: number };
const ForceGraph2D = dynamic(() => import("react-force-graph-2d"), { ssr: false }) as unknown as ForwardRefExoticComponent<
  ForceGraphProps<GraphNode, GraphLink> & RefAttributes<ForceGraphMethods<GraphNode, GraphLink>>
>;

const TYPES: ItemType[] = ["IDEA", "DECISION", "ACTION", "QUESTION"];
const TYPE_COLORS: Record<ItemType, string> = {
  IDEA: "#9bc7b5",
  DECISION: "#e86e55",
  ACTION: "#f0c75e",
  QUESTION: "#7eadd1",
};
const MIN_SEMANTIC_THRESHOLD = 0.35;

export function GraphView({ data }: { data: GraphData }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const graphRef = useRef<ForceGraphMethods<GraphNode, GraphLink> | null>(null);
  const [size, setSize] = useState({ width: 800, height: 560 });
  const [activeTypes, setActiveTypes] = useState<Set<ItemType>>(new Set(TYPES));
  const [topicFilter, setTopicFilter] = useState("all");
  const [showTopicEdges, setShowTopicEdges] = useState(true);
  const [showSemanticEdges, setShowSemanticEdges] = useState(false);
  const [semanticThreshold, setSemanticThreshold] = useState(0.6);
  const [selected, setSelected] = useState<GraphNode | null>(null);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const observer = new ResizeObserver(([entry]) => {
      if (entry) setSize({ width: entry.contentRect.width, height: Math.max(420, entry.contentRect.height) });
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const topics = useMemo(() => {
    const byId = new Map<string, string>();
    for (const node of data.nodes) if (node.topicId && node.topicName) byId.set(node.topicId, node.topicName);
    return [...byId.entries()].sort((a, b) => a[1].localeCompare(b[1]));
  }, [data.nodes]);

  const degreeById = useMemo(() => {
    const counts = new Map<string, number>();
    for (const edge of data.edges) {
      counts.set(edge.source, (counts.get(edge.source) ?? 0) + 1);
      counts.set(edge.target, (counts.get(edge.target) ?? 0) + 1);
    }
    return counts;
  }, [data.edges]);

  const graphData = useMemo(() => {
    const visibleIds = new Set(
      data.nodes
        .filter((node) => activeTypes.has(node.type) && (topicFilter === "all" || node.topicId === topicFilter))
        .map((node) => node.id)
    );
    const nodes = data.nodes.filter((node) => visibleIds.has(node.id));
    const links = data.edges.filter((edge) => {
      if (!visibleIds.has(edge.source) || !visibleIds.has(edge.target)) return false;
      if (edge.kind === "topic") return showTopicEdges;
      if (edge.kind === "semantic") return showSemanticEdges && edge.weight >= semanticThreshold;
      return true;
    });
    return { nodes, links };
  }, [data.nodes, data.edges, activeTypes, topicFilter, showTopicEdges, showSemanticEdges, semanticThreshold]);

  function toggleType(type: ItemType) {
    setActiveTypes((prev) => {
      const next = new Set(prev);
      if (next.has(type)) next.delete(type);
      else next.add(type);
      return next;
    });
  }

  return (
    <div className="graph-page">
      <div className="graph-toolbar">
        <div className="graph-type-filters">
          {TYPES.map((type) => (
            <span
              key={type}
              className={`filter ${activeTypes.has(type) ? "active" : ""}`}
              onClick={() => toggleType(type)}
            >
              {type}
            </span>
          ))}
        </div>
        <select value={topicFilter} onChange={(e) => setTopicFilter(e.target.value)} aria-label="Isolate topic">
          <option value="all">All topics</option>
          {topics.map(([id, name]) => (
            <option key={id} value={id}>
              {name}
            </option>
          ))}
        </select>
        <label className="graph-toggle">
          <input type="checkbox" checked={showTopicEdges} onChange={(e) => setShowTopicEdges(e.target.checked)} />
          Same-topic links
        </label>
        <label className="graph-toggle">
          <input
            type="checkbox"
            checked={showSemanticEdges}
            onChange={(e) => setShowSemanticEdges(e.target.checked)}
          />
          Possible links (semantic)
        </label>
        <input
          type="range"
          min={MIN_SEMANTIC_THRESHOLD}
          max={1}
          step={0.01}
          value={semanticThreshold}
          disabled={!showSemanticEdges}
          onChange={(e) => setSemanticThreshold(Number(e.target.value))}
          aria-label="Semantic similarity threshold"
        />
        <span className="graph-threshold-value">{Math.round(semanticThreshold * 100)}%+</span>
      </div>
      <div className="graph-legend">
        {TYPES.map((type) => (
          <span key={type} className="graph-legend-item">
            <i style={{ background: TYPE_COLORS[type] }} />
            {type}
          </span>
        ))}
        <span className="graph-legend-item"><i className="graph-legend-line graph-legend-line-related" /> Related</span>
        <span className="graph-legend-item"><i className="graph-legend-line graph-legend-line-topic" /> Same topic</span>
        <span className="graph-legend-item"><i className="graph-legend-line graph-legend-line-semantic" /> Possible</span>
      </div>
      <div className="graph-canvas-wrap" ref={containerRef}>
        <ForceGraph2D
          ref={graphRef}
          graphData={graphData}
          width={size.width}
          height={size.height}
          backgroundColor="#f5f4ef"
          nodeLabel={(node) => node.description}
          nodeColor={(node) => TYPE_COLORS[node.type]}
          nodeVal={(node) => 2 + (degreeById.get(node.id) ?? 0) * 0.6}
          linkColor={(link) =>
            link.kind === "related" ? "#172126" : link.kind === "topic" ? "#8b9591" : `rgba(184,90,64,${0.35 + 0.5 * link.weight})`
          }
          linkLineDash={(link) => (link.kind === "topic" ? [4, 3] : link.kind === "semantic" ? [1, 3] : null)}
          linkWidth={(link) => (link.kind === "related" ? 1.6 : 1)}
          onNodeClick={(node) => {
            setSelected(node);
            if (graphRef.current && node.x !== undefined && node.y !== undefined) {
              graphRef.current.centerAt(node.x, node.y, 400);
              graphRef.current.zoom(4, 400);
            }
          }}
          onBackgroundClick={() => setSelected(null)}
        />
      </div>
      {selected ? (
        <aside className="graph-panel">
          <button className="graph-panel-close" onClick={() => setSelected(null)}>
            ✕
          </button>
          <span className="type-label">{selected.type}</span>
          <h3>{selected.description}</h3>
          <div className="card-meta">
            <span>{selected.confidence}</span>
            <span>{selected.owner ?? "Owner unassigned"}</span>
            <span>{selected.topicName ?? "Uncategorized"}</span>
          </div>
          <Link className="back-link" href={`/meetings/${selected.meetingId}`}>
            View source meeting →
          </Link>
        </aside>
      ) : null}
    </div>
  );
}
