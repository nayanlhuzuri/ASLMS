"use client";

/**
 * The relationship graph of linked cases (design portal-cases, decision 11), drawn as a small SVG without a graph
 * library: the case in the first column, linked cases in columns by distance, edges labelled with the link kind;
 * nodes the caller cannot open are grey and not clickable. The links table above it is the accessible version.
 */
import type { GraphEdge, GraphNode, LinkGraph as LinkGraphOut } from "@/lib/api/types";
import { T } from "@/lib/messages";
import { casePath } from "@/lib/refs";

import s from "./case.module.css";

const COL = 230;
const ROW = 56;
const W = 180;
const H = 32;
const PAD = 16;

export interface Placed {
  node: GraphNode;
  col: number;
  row: number;
}

/** Columns by distance from the root (breadth first over undirected edges); unreachable nodes go last. */
export function layout(nodes: GraphNode[], edges: GraphEdge[], rootKey: string | null): Placed[] {
  const dist = new Map<string, number>();
  const root = rootKey && nodes.some((n) => n.key === rootKey) ? rootKey : (nodes[0]?.key ?? null);
  if (root) {
    dist.set(root, 0);
    const queue = [root];
    while (queue.length) {
      const k = queue.shift()!;
      for (const e of edges) {
        const other = e.from === k ? e.to : e.to === k ? e.from : null;
        if (other && !dist.has(other)) {
          dist.set(other, dist.get(k)! + 1);
          queue.push(other);
        }
      }
    }
  }
  const maxD = Math.max(0, ...dist.values());
  const rows = new Map<number, number>();
  return nodes.map((node) => {
    const col = dist.get(node.key) ?? maxD + 1;
    const row = rows.get(col) ?? 0;
    rows.set(col, row + 1);
    return { node, col, row };
  });
}

function label(n: GraphNode): string {
  const text = n.case_no_text ?? n.case?.case_no_text ?? n.case?.ref_no ?? n.key;
  return text.length > 24 ? text.slice(0, 23) + "…" : text;
}

export function LinkGraph({ graph, rootId }: { graph: LinkGraphOut; rootId: string | null }) {
  const rootKey = graph.nodes.find((n) => n.case?.id === rootId)?.key ?? null;
  const placed = layout(graph.nodes, graph.edges, rootKey);
  const at = new Map(placed.map((p) => [p.node.key, p]));
  const cols = Math.max(1, ...placed.map((p) => p.col + 1));
  const rows = Math.max(1, ...placed.map((p) => p.row + 1));
  const width = cols * COL + PAD;
  const height = rows * ROW + PAD;
  const x = (p: Placed) => PAD + p.col * COL;
  const y = (p: Placed) => PAD + p.row * ROW;
  return (
    <figure className="stack">
      <div className={s.graph}>
        <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img" aria-label={T.case.graph}>
          {graph.edges.map((e, i) => {
            const a = at.get(e.from);
            const b = at.get(e.to);
            if (!a || !b) return null;
            const x1 = x(a) + W / 2;
            const y1 = y(a) + H / 2;
            const x2 = x(b) + W / 2;
            const y2 = y(b) + H / 2;
            return (
              <g key={i} data-edge={`${e.from}->${e.to}`}>
                <line x1={x1} y1={y1} x2={x2} y2={y2} stroke="#8892a0" strokeWidth={1.5} />
                <text x={(x1 + x2) / 2} y={(y1 + y2) / 2 - 4} textAnchor="middle" fill="#4f5968">
                  {e.kind}
                </text>
              </g>
            );
          })}
          {placed.map((p) => {
            const isRoot = p.node.key === rootKey;
            const box = (
              <g data-node={p.node.key}>
                <rect
                  x={x(p)}
                  y={y(p)}
                  width={W}
                  height={H}
                  rx={6}
                  fill={isRoot ? "#15284a" : p.node.visible ? "#e6ebf3" : "#eeeeee"}
                  stroke={p.node.visible ? "#1f3a66" : "#b5b5b5"}
                />
                <text x={x(p) + W / 2} y={y(p) + H / 2 + 4} textAnchor="middle" fill={isRoot ? "#ffffff" : p.node.visible ? "#1b2330" : "#767676"}>
                  {label(p.node)}
                </text>
              </g>
            );
            return p.node.visible && p.node.case && !isRoot ? (
              <a key={p.node.key} href={casePath(p.node.case.ref_no)} aria-label={label(p.node)}>
                {box}
              </a>
            ) : (
              <g key={p.node.key}>{box}</g>
            );
          })}
        </svg>
      </div>
      {graph.truncated ? <figcaption className="muted">{T.case.graphTruncated}</figcaption> : null}
    </figure>
  );
}
