import React, { useEffect, useMemo } from "react";
import ForceGraph3D from "react-force-graph-3d";
import * as THREE from "three";

function clusterColor(clusterId) {
  let hash = 0;
  for (let i = 0; i < clusterId.length; i += 1) hash = clusterId.charCodeAt(i) + ((hash << 5) - hash);
  const hue = Math.abs(hash) % 360;
  return `hsl(${hue} 65% 55%)`;
}

function makeYouAreHereSprite() {
  const canvas = document.createElement("canvas");
  canvas.width = 256;
  canvas.height = 64;
  const ctx = canvas.getContext("2d");
  if (!ctx) return null;
  ctx.fillStyle = "rgba(0,0,0,0.65)";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = "#f8fafc";
  ctx.font = "bold 28px sans-serif";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText("You are here", canvas.width / 2, canvas.height / 2);
  const texture = new THREE.CanvasTexture(canvas);
  const material = new THREE.SpriteMaterial({ map: texture, transparent: true });
  const sprite = new THREE.Sprite(material);
  sprite.scale.set(42, 10, 1);
  sprite.position.set(0, 14, 0);
  return sprite;
}

function makeNodeLabelSprite(text, zoomTier = "mid") {
  const safeText = (text || "").trim();
  const canvas = document.createElement("canvas");
  canvas.width = 960;
  canvas.height = 220;
  const ctx = canvas.getContext("2d");
  if (!ctx) return null;
  const fontSize = zoomTier === "near" ? 44 : zoomTier === "mid" ? 38 : 32;
  const lineHeight = Math.round(fontSize * 1.2);
  const horizontalPadding = 40;
  const verticalPadding = 26;
  const maxTextWidth = canvas.width - horizontalPadding * 2;
  const labelWidth = zoomTier === "near" ? 118 : zoomTier === "mid" ? 102 : 88;
  const labelHeight = zoomTier === "near" ? 16 : zoomTier === "mid" ? 14 : 12.5;

  ctx.font = `${fontSize}px sans-serif`;
  const words = safeText.split(/\s+/).filter(Boolean);
  const lines = [];
  let current = "";
  for (const word of words) {
    const test = current ? `${current} ${word}` : word;
    if (ctx.measureText(test).width <= maxTextWidth) {
      current = test;
    } else if (!current) {
      current = word;
    } else {
      lines.push(current);
      current = word;
      if (lines.length === 2) break;
    }
  }
  if (current && lines.length < 2) lines.push(current);
  if (lines.length === 0) lines.push("");

  if (lines.length === 2) {
    while (ctx.measureText(lines[1]).width > maxTextWidth && lines[1].length > 1) {
      lines[1] = lines[1].slice(0, -1).trimEnd();
    }
    if (lines[1].length < safeText.length) lines[1] = `${lines[1]}...`;
  }

  const usedHeight = verticalPadding * 2 + lineHeight * lines.length;
  canvas.height = Math.max(usedHeight, 140);

  // Re-apply context state after resizing canvas.
  ctx.font = `${fontSize}px sans-serif`;
  ctx.fillStyle = "rgba(2,6,23,0.72)";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = "#dbeafe";
  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  const startY = (canvas.height - lineHeight * lines.length) / 2;
  lines.forEach((line, idx) => {
    ctx.fillText(line, canvas.width / 2, startY + idx * lineHeight);
  });
  const texture = new THREE.CanvasTexture(canvas);
  const material = new THREE.SpriteMaterial({ map: texture, transparent: true });
  const sprite = new THREE.Sprite(material);
  sprite.scale.set(labelWidth, labelHeight, 1);
  sprite.position.set(0, 10, 0);
  return sprite;
}

export default function Map3D({
  graph,
  selectedNodeId,
  yourInsightNodeId,
  zoomTier,
  supporters,
  challengers,
  onNodeClick,
  onBackgroundClick,
  graphRef,
  width,
  height,
}) {
  const showYouAreHereOnNode = yourInsightNodeId != null;
  const supporterIds = useMemo(() => new Set((supporters || []).map((n) => n.id)), [supporters]);
  const challengerIds = useMemo(() => new Set((challengers || []).map((n) => n.id)), [challengers]);
  const labelModulo = zoomTier === "near" ? 2 : zoomTier === "mid" ? 5 : 12;

  const graphData = useMemo(() => {
    const nodes = (graph.nodes || []).map((n) => ({
      ...n,
      id: n.id,
      color: clusterColor(n.cluster_id || "x"),
    }));
    const nodeById = new Map(nodes.map((n) => [String(n.id), n]));
    const links = (graph.edges || [])
      .map((e) => {
        const srcId = String(e.src);
        const tgtId = String(e.dst);
        const source = nodeById.get(srcId);
        const target = nodeById.get(tgtId);
        if (!source || !target) return null;
        return { source, target, weight: e.weight };
      })
      .filter(Boolean);
    return { nodes, links };
  }, [graph]);

  useEffect(() => {
    const fg = graphRef?.current;
    if (!fg) return;

    const linkForce = fg.d3Force("link");
    if (linkForce) {
      linkForce.distance((link) => {
        const w = Number(link.weight || 0);
        return 45 + (1 - Math.max(0, Math.min(1, w))) * 110;
      });
      linkForce.strength((link) => {
        const w = Number(link.weight || 0);
        return 0.15 + Math.max(0, Math.min(1, w)) * 0.85;
      });
    }

    const chargeForce = fg.d3Force("charge");
    if (chargeForce) {
      chargeForce.strength(-55);
      chargeForce.distanceMax(260);
    }

    const centerForce = fg.d3Force("center");
    if (centerForce && centerForce.strength) {
      centerForce.strength(0.12);
    }

    const controls = fg.controls?.();
    if (controls) {
      controls.enableZoom = true;
      controls.zoomSpeed = 2.0;
      controls.minDistance = 18;
      controls.maxDistance = 1800;
    }
  }, [graphData, graphRef]);

  return (
    <ForceGraph3D
      ref={graphRef}
      width={width}
      height={height}
      controlType="orbit"
      graphData={graphData}
      backgroundColor="#090b10"
      nodeLabel={(n) => `${n.text}`}
      nodeRelSize={6}
      linkOpacity={0.2}
      linkWidth={(l) => Math.max(0.3, l.weight * 2)}
      enableNodeDrag={false}
      nodeColor={(node) => {
        if (node.id === selectedNodeId) return "#f8fafc";
        if (supporterIds.has(node.id)) return "#22c55e";
        if (challengerIds.has(node.id)) return "#f43f5e";
        return node.color;
      }}
      nodeThreeObject={(node) => {
        const group = new THREE.Group();
        let hasObject = false;

        if (showYouAreHereOnNode && node.id === yourInsightNodeId) {
          const ring = new THREE.Mesh(
            new THREE.RingGeometry(6.5, 8.5, 48),
            new THREE.MeshBasicMaterial({ color: 0xf8fafc, side: THREE.DoubleSide, transparent: true, opacity: 0.95 }),
          );
          ring.lookAt(new THREE.Vector3(0, 0, 1));
          group.add(ring);
          const marker = makeYouAreHereSprite();
          if (marker) group.add(marker);
          hasObject = true;
        }

        const nodeText = node?.text || "";
        const hashBase = String(node.id || nodeText).length + nodeText.length;
        const shouldShowLabel =
          node.id === selectedNodeId ||
          node.id === yourInsightNodeId ||
          hashBase % labelModulo === 0;

        if (shouldShowLabel) {
          const label = makeNodeLabelSprite(nodeText, zoomTier);
          if (label) {
            label.position.set(0, (node.id === yourInsightNodeId ? 18 : 11), 0);
            group.add(label);
            hasObject = true;
          }
        }

        return hasObject ? group : null;
      }}
      nodeThreeObjectExtend
      onNodeClick={onNodeClick}
      onBackgroundClick={onBackgroundClick}
      d3AlphaDecay={0.06}
      d3VelocityDecay={0.18}
      cooldownTicks={120}
    />
  );
}
