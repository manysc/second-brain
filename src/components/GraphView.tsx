"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import type { ForwardRefExoticComponent, RefAttributes } from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { ForceGraphMethods, ForceGraphProps } from "react-force-graph-2d";
import type { GraphData, GraphEdge, GraphNode, ItemType, TopicPriorityLevel } from "@/lib/domain";

// react-force-graph's default export is a generic component; next/dynamic can't infer that
// generic, so we re-assert the concrete instantiation we actually use.
// Topic nodes are synthesized client-side for the selected topic and its related topics; they are not items.
type TopicNode = { kind: "topic"; id: string; topicId: string; name: string; itemCount: number; selected: boolean };
type ItemNode = GraphNode & { kind?: "item" };
type ViewNode = ItemNode | TopicNode;
type GraphLink = { kind: GraphEdge["kind"] | "topic-related" | "topic-member"; weight: number };
const ForceGraph2D = dynamic(() => import("react-force-graph-2d"), { ssr: false }) as unknown as ForwardRefExoticComponent<
  ForceGraphProps<ViewNode, GraphLink> & RefAttributes<ForceGraphMethods<ViewNode, GraphLink>>
>;

const TOPIC_NODE_COLOR = "#172126";
const topicNodeId = (topicId: string) => `topic-node:${topicId}`;
const isTopicNode = (node: ViewNode): node is TopicNode => node.kind === "topic";

const TYPES: ItemType[] = ["IDEA", "DECISION", "ACTION", "QUESTION"];
const TYPE_COLORS: Record<ItemType, string> = {
  IDEA: "#9bc7b5",
  DECISION: "#e86e55",
  ACTION: "#f0c75e",
  QUESTION: "#7eadd1",
};
const PRIORITY_LEVELS: TopicPriorityLevel[] = ["CRITICAL", "MAJOR", "MINOR"];
const PRIORITY_RING_COLORS: Record<TopicPriorityLevel, string> = {
  CRITICAL: "#a3372a",
  MAJOR: "#a8791f",
  MINOR: "#4f7a63",
};
const MIN_SEMANTIC_THRESHOLD = 0.35;
const NODE_REL_SIZE = 3;
const TOPIC_NODE_HALF = 8;

export function GraphView({ data }: { data: GraphData }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const graphRef = useRef<ForceGraphMethods<ViewNode, GraphLink> | null>(null);
  const [size, setSize] = useState({ width: 800, height: 560 });
  const [activeTypes, setActiveTypes] = useState<Set<ItemType>>(new Set(TYPES));
  const [activePriorities, setActivePriorities] = useState<Set<TopicPriorityLevel>>(new Set(PRIORITY_LEVELS));
  const [topicFilter, setTopicFilter] = useState("all");
  const [showTopicEdges, setShowTopicEdges] = useState(true);
  const [showSemanticEdges, setShowSemanticEdges] = useState(false);
  const [semanticThreshold, setSemanticThreshold] = useState(0.6);
  const [selected, setSelected] = useState<ViewNode | null>(null);

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
      // same-topic edges form a clique per topic, so counting them would size every item by topic size
      if (edge.kind === "topic") continue;
      counts.set(edge.source, (counts.get(edge.source) ?? 0) + 1);
      counts.set(edge.target, (counts.get(edge.target) ?? 0) + 1);
    }
    return counts;
  }, [data.edges]);

  const selectedTopicId = topicFilter !== "all" ? topicFilter : (selected?.topicId ?? null);

  const graphData = useMemo(() => {
    const visibleIds = new Set(
      data.nodes
        .filter(
          (node) =>
            activeTypes.has(node.type) &&
            (topicFilter === "all" || node.topicId === topicFilter) &&
            (node.priority === null || activePriorities.has(node.priority))
        )
        .map((node) => node.id)
    );
    const nodes: ViewNode[] = data.nodes.filter((node) => visibleIds.has(node.id));
    const links: Array<{ source: string; target: string } & GraphLink> = data.edges.filter((edge) => {
      if (!visibleIds.has(edge.source) || !visibleIds.has(edge.target)) return false;
      if (edge.kind === "topic") return showTopicEdges;
      if (edge.kind === "semantic") return showSemanticEdges && edge.weight >= semanticThreshold;
      return true;
    });

    // the selected topic and the topics most related to it become nodes of their own
    if (selectedTopicId) {
      const topicsById = new Map(data.topics.map((topic) => [topic.id, topic]));
      const current = topicsById.get(selectedTopicId);
      if (current) {
        nodes.push({ kind: "topic", id: topicNodeId(current.id), topicId: current.id, name: current.name, itemCount: current.itemCount, selected: true });
        for (const node of data.nodes) {
          if (node.topicId === current.id && visibleIds.has(node.id)) {
            links.push({ source: topicNodeId(current.id), target: node.id, kind: "topic-member", weight: 1 });
          }
        }
        for (const link of data.topicLinks) {
          const related = link.source === current.id ? topicsById.get(link.target) : undefined;
          if (!related) continue;
          nodes.push({ kind: "topic", id: topicNodeId(related.id), topicId: related.id, name: related.name, itemCount: related.itemCount, selected: false });
          links.push({ source: topicNodeId(current.id), target: topicNodeId(related.id), kind: "topic-related", weight: link.similarity });
        }
      }
    }
    return { nodes, links };
  }, [data.nodes, data.edges, data.topics, data.topicLinks, activeTypes, activePriorities, topicFilter, selectedTopicId, showTopicEdges, showSemanticEdges, semanticThreshold]);

  // graph-space radius of an item node; must match nodeVal below (radius = sqrt(val) * nodeRelSize)
  const itemVal = (id: string) => 1.5 + Math.min(Math.sqrt(degreeById.get(id) ?? 0), 4);

  useEffect(() => {
    const graph = graphRef.current;
    if (!graph) return;
    // spread the dense same-topic clusters out instead of letting them collapse into a ball
    graph.d3Force("charge")?.strength(-70);
    graph.d3Force("link")?.distance((link: GraphLink) => (link.kind === "topic" ? 70 : link.kind === "topic-related" ? 90 : 35));
    graph.d3ReheatSimulation();
  }, [graphData]);

  function toggleType(type: ItemType) {
    setActiveTypes((prev) => {
      const next = new Set(prev);
      if (next.has(type)) next.delete(type);
      else next.add(type);
      return next;
    });
  }

  function togglePriority(level: TopicPriorityLevel) {
    setActivePriorities((prev) => {
      const next = new Set(prev);
      if (next.has(level)) next.delete(level);
      else next.add(level);
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
        <div className="graph-type-filters">
          {PRIORITY_LEVELS.map((level) => (
            <span
              key={level}
              className={`filter ${activePriorities.has(level) ? "active" : ""}`}
              onClick={() => togglePriority(level)}
            >
              {level}
            </span>
          ))}
        </div>
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
        <span className="graph-legend-item"><i style={{ background: TOPIC_NODE_COLOR, transform: "rotate(45deg)" }} /> Topic / related topic</span>
        {PRIORITY_LEVELS.map((level) => (
          <span key={level} className="graph-legend-item">
            <i style={{ background: "transparent", border: `2px solid ${PRIORITY_RING_COLORS[level]}` }} />
            {level} topic ring
          </span>
        ))}
      </div>
      <div className="graph-canvas-wrap" ref={containerRef}>
        <ForceGraph2D
          ref={graphRef}
          graphData={graphData}
          width={size.width}
          height={size.height}
          backgroundColor="#f5f4ef"
          nodeLabel={(node) =>
            isTopicNode(node) ? `${node.name} (${node.itemCount} items)` : node.description
          }
          nodeColor={(node) => (isTopicNode(node) ? TOPIC_NODE_COLOR : TYPE_COLORS[node.type])}
          nodeRelSize={NODE_REL_SIZE}
          nodeVal={(node) => (isTopicNode(node) ? 4 : itemVal(node.id))}
          linkColor={(link) =>
            link.kind === "related" || link.kind === "topic-related"
              ? "#172126"
              : link.kind === "topic" || link.kind === "topic-member"
                ? "#8b9591"
                : `rgba(184,90,64,${0.35 + 0.5 * link.weight})`
          }
          linkLineDash={(link) =>
            link.kind === "topic" || link.kind === "topic-member" ? [4, 3] : link.kind === "semantic" ? [1, 3] : null
          }
          linkLabel={(link) => (link.kind === "topic-related" ? `${Math.round(link.weight * 100)}% similar` : "")}
          linkWidth={(link) => (link.kind === "topic-related" ? 1 + 2 * link.weight : link.kind === "related" ? 1.6 : 1)}
          nodeCanvasObjectMode={(node) => (isTopicNode(node) ? "replace" : "after")}
          nodePointerAreaPaint={(node, color, ctx) => {
            if (!isTopicNode(node) || node.x === undefined || node.y === undefined) return;
            ctx.fillStyle = color;
            ctx.fillRect(node.x - TOPIC_NODE_HALF, node.y - TOPIC_NODE_HALF, TOPIC_NODE_HALF * 2, TOPIC_NODE_HALF * 2);
          }}
          nodeCanvasObject={(node, ctx, globalScale) => {
            if (node.x === undefined || node.y === undefined) return;
            if (isTopicNode(node)) {
              // diamond + name label, so topics read as a different kind of thing than item circles
              const half = node.selected ? TOPIC_NODE_HALF : TOPIC_NODE_HALF - 2;
              ctx.beginPath();
              ctx.moveTo(node.x, node.y - half);
              ctx.lineTo(node.x + half, node.y);
              ctx.lineTo(node.x, node.y + half);
              ctx.lineTo(node.x - half, node.y);
              ctx.closePath();
              ctx.fillStyle = node.selected ? TOPIC_NODE_COLOR : "#f5f4ef";
              ctx.fill();
              ctx.strokeStyle = TOPIC_NODE_COLOR;
              ctx.lineWidth = 1.5 / globalScale;
              ctx.stroke();

              const label = node.name.length > 28 ? `${node.name.slice(0, 27)}…` : node.name;
              const fontSize = 11 / globalScale;
              ctx.font = `${node.selected ? "600 " : ""}${fontSize}px sans-serif`;
              const width = ctx.measureText(label).width;
              const labelY = node.y + half + fontSize;
              ctx.fillStyle = "rgba(245,244,239,0.85)";
              ctx.fillRect(node.x - width / 2 - 2 / globalScale, labelY - fontSize / 2 - 1 / globalScale, width + 4 / globalScale, fontSize + 2 / globalScale);
              ctx.textAlign = "center";
              ctx.textBaseline = "middle";
              ctx.fillStyle = TOPIC_NODE_COLOR;
              ctx.fillText(label, node.x, labelY);
              return;
            }
            // priority is shown as a ring around the node, never as size - size already encodes
            // connectivity (degree), and conflating the two would imply centrality = importance
            if (!node.priority) return;
            const radius = Math.sqrt(itemVal(node.id)) * NODE_REL_SIZE;
            ctx.beginPath();
            ctx.arc(node.x, node.y, radius + 1.5, 0, 2 * Math.PI);
            ctx.strokeStyle = PRIORITY_RING_COLORS[node.priority];
            ctx.lineWidth = (node.priority === "CRITICAL" ? 2 : 1.2) / Math.max(1, globalScale / 2);
            ctx.stroke();
          }}
          onNodeClick={(node) => {
            // choosing a topic node re-centers the graph on that topic and its own related topics
            if (isTopicNode(node)) setTopicFilter(node.topicId);
            setSelected(node);
            if (graphRef.current && node.x !== undefined && node.y !== undefined) {
              graphRef.current.centerAt(node.x, node.y, 400);
              graphRef.current.zoom(isTopicNode(node) ? 2 : 2.5, 400);
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
          {isTopicNode(selected) ? (
            <>
              <span className="type-label">TOPIC</span>
              <h3>{selected.name}</h3>
              <div className="card-meta">
                <span>{selected.itemCount} items</span>
              </div>
              <Link className="back-link" href={`/topics/${selected.topicId}`}>
                Open topic →
              </Link>
            </>
          ) : (
            <>
              <span className="type-label">{selected.type}</span>
              <h3>{selected.description}</h3>
              <div className="card-meta">
                <span>{selected.confidence}</span>
                <span>{selected.owner ?? "Owner unassigned"}</span>
                <span>{selected.topicName ?? "Uncategorized"}</span>
                {selected.priority ? <span>{selected.priority} priority</span> : null}
              </div>
              <Link className="back-link" href={`/meetings/${selected.meetingId}`}>
                View source meeting →
              </Link>
            </>
          )}
        </aside>
      ) : null}
    </div>
  );
}
