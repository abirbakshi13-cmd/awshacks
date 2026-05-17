import { useRef, useState, useEffect, useMemo, useCallback } from 'react';
import { motion } from 'framer-motion';
import ForceGraph2D from 'react-force-graph-2d';

const HOLDING_COLOR = '#f59e0b';
const RELATED_COLOR = '#4b5563';
const RING_COLOR    = '#f0f2f8';
const LINK_COLOR    = 'rgba(148,163,184,0.28)';
const LABEL_COLOR   = '#f0f2f8';
const BG_COLOR      = '#181c25';

const HOLDING_R = 14;
const RELATED_R = 8;

function nodeRadius(node, holdingSet) {
  return holdingSet.has(node.id) ? HOLDING_R : RELATED_R;
}

export default function RelationshipGraph({
  graphData,
  holdings,
  selectedTicker,
  setSelectedTicker,
}) {
  const containerRef = useRef(null);
  const [dims, setDims] = useState({ width: 0, height: 0 });

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      setDims({ width, height });
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const holdingSet = useMemo(
    () => new Set((holdings ?? []).map((h) => h.ticker)),
    [holdings]
  );

  const fgData = useMemo(() => {
    if (!graphData) return null;
    return {
      nodes: graphData.nodes.map((n) => ({
        ...n,
        val: holdingSet.has(n.id) ? 12 : 3,
      })),
      links: graphData.edges.map((e) => ({
        source: e.from,
        target: e.to,
        weight: e.weight,
      })),
    };
  }, [graphData, holdingSet]);

  const drawNode = useCallback(
    (node, ctx) => {
      const isHolding = holdingSet.has(node.id);
      const isSelected = node.id === selectedTicker;
      const r = isHolding ? HOLDING_R : RELATED_R;

      if (isSelected) {
        ctx.beginPath();
        ctx.arc(node.x, node.y, r + 4, 0, 2 * Math.PI);
        ctx.strokeStyle = RING_COLOR;
        ctx.lineWidth = 2;
        ctx.stroke();
      }

      ctx.beginPath();
      ctx.arc(node.x, node.y, r, 0, 2 * Math.PI);
      ctx.fillStyle = isHolding ? HOLDING_COLOR : RELATED_COLOR;
      ctx.fill();

      ctx.font = `bold ${isHolding ? 11 : 9}px system-ui,sans-serif`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillStyle = LABEL_COLOR;
      ctx.fillText(node.label || node.id, node.x, node.y);
    },
    [holdingSet, selectedTicker]
  );

  const paintPointerArea = useCallback(
    (node, color, ctx) => {
      const r = nodeRadius(node, holdingSet);
      ctx.beginPath();
      ctx.arc(node.x, node.y, r, 0, 2 * Math.PI);
      ctx.fillStyle = color;
      ctx.fill();
    },
    [holdingSet]
  );

  // Single root element so the entry animation fires exactly once,
  // regardless of the graphData null → loaded transition.
  return (
    <motion.div
      ref={containerRef}
      className={`panel panel-graph${!graphData ? ' rg-empty' : ''}`}
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2, ease: 'easeOut', delay: 0.06 }}
    >
      {!graphData && 'Loading graph…'}
      {graphData && dims.width > 0 && (
        <ForceGraph2D
          graphData={fgData}
          width={dims.width}
          height={dims.height}
          backgroundColor={BG_COLOR}
          nodeCanvasObject={drawNode}
          nodeCanvasObjectMode={() => 'replace'}
          nodePointerAreaPaint={paintPointerArea}
          linkWidth={(link) => link.weight * 4}
          linkColor={() => LINK_COLOR}
          onNodeClick={(node) => setSelectedTicker(node.id)}
          nodeLabel={(node) => node.label || node.id}
          cooldownTicks={150}
          d3AlphaDecay={0.03}
          d3VelocityDecay={0.3}
        />
      )}
    </motion.div>
  );
}
