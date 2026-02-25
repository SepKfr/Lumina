import React, { useEffect, useMemo } from "react";
import ForceGraph3D from "react-force-graph-3d";
import * as THREE from "three";
import { forceX, forceY, forceZ } from "d3-force-3d";

function clusterColor(clusterId) {
  let hash = 0;
  for (let i = 0; i < clusterId.length; i += 1) hash = clusterId.charCodeAt(i) + ((hash << 5) - hash);
  const hue = (Math.abs(hash) % 360) / 360;
  const s = 0.65;
  const l = 0.55;
  const c = (1 - Math.abs(2 * l - 1)) * s;
  const x = c * (1 - Math.abs(((hue * 6) % 2) - 1));
  const m = l - c / 2;
  let r = 0, g = 0, b = 0;
  if (hue < 1/6) { r = c; g = x; } else if (hue < 2/6) { r = x; g = c; } else if (hue < 3/6) { g = c; b = x; } else if (hue < 4/6) { g = x; b = c; } else if (hue < 5/6) { r = x; b = c; } else { r = c; b = x; }
  const rr = Math.round((r + m) * 255);
  const gg = Math.round((g + m) * 255);
  const bb = Math.round((b + m) * 255);
  return `#${rr.toString(16).padStart(2, "0")}${gg.toString(16).padStart(2, "0")}${bb.toString(16).padStart(2, "0")}`;
}

/** Deterministic string -> number in [0, 1). */
function hashStr(s) {
  let h = 0;
  const str = String(s || "");
  for (let i = 0; i < str.length; i += 1) h = str.charCodeAt(i) + ((h << 5) - h);
  return (Math.abs(h) % 10000) / 10000;
}

/** Smooth floating drift: base position + slow sine waves with per-node phase so motion feels natural. */
function floatingPosition(node, tSec) {
  const phase = hashStr(String(node.id)) * Math.PI * 2;
  const amp = 5;
  const period = 6;
  const x = (node.baseX ?? node.x) + Math.sin((tSec / period) * Math.PI * 2 + phase) * amp;
  const y = (node.baseY ?? node.y) + Math.sin((tSec / period) * Math.PI * 2 + phase + 1.9) * amp;
  const z = (node.baseZ ?? node.z) + Math.sin((tSec / period) * Math.PI * 2 + phase + 3.1) * amp * 0.5;
  return { x, y, z };
}

/** Position node in 3D by level1 (x), level2 (y), level3 (z). Same L1/L2/L3 cluster together. Scale and jitter to avoid exact overlap. */
function topicPosition(node, index) {
  const L1 = node.level1 || node.metadata_json?.level1 || "general";
  const L2 = node.level2 || node.metadata_json?.level2 || L1;
  const L3 = node.level3 || node.metadata_json?.level3 || L2;
  const scale = 120;
  const jitter = 8;
  const x = (hashStr(L1) - 0.5) * scale * 2 + (hashStr(L1 + "x") - 0.5) * jitter;
  const y = (hashStr(L2) - 0.5) * scale * 2 + (hashStr(L2 + "y") - 0.5) * jitter;
  const z = (hashStr(L3) - 0.5) * scale * 1.5 + (hashStr(L3 + "z") - 0.5) * jitter;
  return { x, y, z };
}

/** 3D bubble sphere — lit material with soft highlight so it reads as round and dimensional. */
function makeBubbleSphere(nodeColor, radius = 5) {
  let color;
  if (typeof nodeColor === "string") {
    if (nodeColor.startsWith("#")) {
      const c = parseInt(nodeColor.slice(1), 16);
      color = new THREE.Color((c >> 16) / 255, (c >> 8 & 255) / 255, (c & 255) / 255);
    } else {
      color = new THREE.Color(nodeColor);
    }
  } else {
    color = new THREE.Color(nodeColor);
  }
  const material = new THREE.MeshPhongMaterial({
    color,
    emissive: color.clone().multiplyScalar(0.15),
    specular: new THREE.Color(0.4, 0.4, 0.45),
    shininess: 50,
    flatShading: false,
  });
  const geometry = new THREE.SphereGeometry(radius, 32, 32);
  const mesh = new THREE.Mesh(geometry, material);
  return mesh;
}

function edgeColor(edgeType) {
  if (edgeType === "support") return "#22c55e";
  if (edgeType === "oppose") return "#f43f5e";
  if (edgeType === "neutral_similarity") return "#94a3b8";
  if (edgeType === "idea_similarity_fallback") return "#64748b";
  return "#38bdf8";
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

function makeNodeLabelSprite(text, zoomTier = "mid", debugLines = null) {
  const safeText = (text || "").trim();
  const canvas = document.createElement("canvas");
  canvas.width = 960;
  const hasDebug = debugLines && debugLines.length > 0;
  canvas.height = hasDebug ? 280 : 220;
  const ctx = canvas.getContext("2d");
  if (!ctx) return null;
  const fontSize = zoomTier === "near" ? 44 : zoomTier === "mid" ? 38 : 32;
  const lineHeight = Math.round(fontSize * 1.2);
  const horizontalPadding = 40;
  const verticalPadding = 26;
  const maxTextWidth = canvas.width - horizontalPadding * 2;
  const labelWidth = zoomTier === "near" ? 118 : zoomTier === "mid" ? 102 : 88;
  let labelHeight = zoomTier === "near" ? 16 : zoomTier === "mid" ? 14 : 12.5;

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

  let usedHeight = verticalPadding * 2 + lineHeight * lines.length;
  if (hasDebug) {
    const debugFontSize = Math.round(fontSize * 0.45);
    usedHeight += 8 + debugFontSize * debugLines.length;
  }
  canvas.height = Math.max(usedHeight, 140);

  // Re-apply context state after resizing canvas.
  ctx.font = `${fontSize}px sans-serif`;
  ctx.fillStyle = "#dbeafe";
  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  let startY = (canvas.height - lineHeight * lines.length) / 2;
  if (hasDebug) startY = verticalPadding;
  lines.forEach((line, idx) => {
    ctx.fillText(line, canvas.width / 2, startY + idx * lineHeight);
  });
  if (hasDebug && debugLines.length > 0) {
    const debugFontSize = Math.round(fontSize * 0.45);
    ctx.font = `${debugFontSize}px sans-serif`;
    ctx.fillStyle = "rgba(148, 163, 184, 0.95)";
    const debugY = startY + lineHeight * lines.length + 8;
    debugLines.forEach((d, idx) => {
      ctx.fillText(d, canvas.width / 2, debugY + idx * debugFontSize);
    });
    labelHeight += (debugLines.length * debugFontSize) / 10;
  }
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
  debugMode = false,
}) {
  const showYouAreHereOnNode = yourInsightNodeId != null;
  const supporterIds = useMemo(() => new Set((supporters || []).map((n) => n.id)), [supporters]);
  const challengerIds = useMemo(() => new Set((challengers || []).map((n) => n.id)), [challengers]);
  const labelModulo = zoomTier === "near" ? 2 : zoomTier === "mid" ? 5 : 12;

  const graphData = useMemo(() => {
    const rawNodes = graph.nodes || [];
    const nodes = rawNodes.map((n, idx) => {
      const pos = topicPosition(n, idx);
      return {
        ...n,
        id: n.id,
        color: clusterColor(n.cluster_id || "x"),
        x: pos.x,
        y: pos.y,
        z: pos.z,
        baseX: pos.x,
        baseY: pos.y,
        baseZ: pos.z,
        // No fx,fy,fz — let simulation pull toward base for gentle bubble drift
      };
    });
    const nodeById = new Map(nodes.map((n) => [String(n.id), n]));
    // Keep links in data for backend/API but do not use for layout — layout is by L1/L2/L3 only. Links are hidden in UI.
    const links = (graph.edges || [])
      .map((e) => {
        const srcId = String(e.src);
        const tgtId = String(e.dst);
        const source = nodeById.get(srcId);
        const target = nodeById.get(tgtId);
        if (!source || !target) return null;
        return { source, target, weight: e.weight, edge_type: e.edge_type || "idea_similarity" };
      })
      .filter(Boolean);
    return { nodes, links };
  }, [graph]);

  useEffect(() => {
    const fg = graphRef?.current;
    if (!fg) return;

    const linkForce = fg.d3Force("link");
    if (linkForce) {
      linkForce.distance(0);
      linkForce.strength(0);
    }

    const chargeForce = fg.d3Force("charge");
    if (chargeForce) {
      chargeForce.strength(-12);
    }

    const centerForce = fg.d3Force("center");
    if (centerForce && centerForce.strength) {
      centerForce.strength(0);
    }

    // Softer pull toward topic position (layout only; we overlay smooth drift in nodePositionUpdate)
    fg.d3Force("x", forceX((d) => d.baseX).strength(0.022));
    fg.d3Force("y", forceY((d) => d.baseY).strength(0.022));
    fg.d3Force("z", forceZ((d) => d.baseZ).strength(0.022));

    // No random drift force — it caused jitter; drift is done via nodePositionUpdate with smooth sine waves

    if (typeof fg.d3AlphaMin === "function") {
      fg.d3AlphaMin(0); // keep simulation running; don't stop when alpha decays
    }
    if (typeof fg.d3AlphaDecay === "function") {
      fg.d3AlphaDecay(0.018);
    }

    const controls = fg.controls?.();
    if (controls) {
      controls.enableZoom = true;
      controls.zoomSpeed = 2.0;
      controls.minDistance = 18;
      controls.maxDistance = 1800;
    }
  }, [graphData, graphRef]);

  // Initial camera: bring graph into view (avoid "far away" / glass wedgie)
  useEffect(() => {
    const fg = graphRef?.current;
    const nodes = graphData?.nodes || [];
    if (!fg || nodes.length === 0) return;
    if (typeof fg.cameraPosition !== "function") return;
    fg.cameraPosition({ x: 0, y: 0, z: 300 }, { x: 0, y: 0, z: 0 }, 0);
  }, [graphRef, graphData?.nodes?.length]);

  return (
    <ForceGraph3D
      ref={graphRef}
      width={width}
      height={height}
      controlType="orbit"
      graphData={graphData}
      backgroundColor="#090b10"
      nodeLabel={(n) => {
        const base = n.text || "";
        if (!debugMode) return base;
        const l1 = n.level1 || n.metadata_json?.level1 || "—";
        const l2 = n.level2 || n.metadata_json?.level2 || "—";
        const l3 = n.level3 || n.metadata_json?.level3 || "—";
        return `${base}\n\nL1: ${l1}\nL2: ${l2}\nL3: ${l3}`;
      }}
      nodeRelSize={6}
      linkOpacity={0}
      linkWidth={0}
      enableNodeDrag={false}
      nodeColor={(node) => {
        if (node.id === selectedNodeId) return "#f8fafc";
        if (supporterIds.has(node.id)) return "#22c55e";
        if (challengerIds.has(node.id)) return "#f43f5e";
        return node.color;
      }}
      nodeThreeObject={(node) => {
        const group = new THREE.Group();
        const nodeColor =
          node.id === selectedNodeId
            ? "#f8fafc"
            : supporterIds.has(node.id)
              ? "#22c55e"
              : challengerIds.has(node.id)
                ? "#f43f5e"
                : node.color || clusterColor(node.cluster_id || "x");
        const bubble = makeBubbleSphere(nodeColor, 5.5);
        group.add(bubble);

        if (showYouAreHereOnNode && node.id === yourInsightNodeId) {
          const ring = new THREE.Mesh(
            new THREE.RingGeometry(6.5, 8.5, 48),
            new THREE.MeshBasicMaterial({ color: 0xf8fafc, side: THREE.DoubleSide, transparent: true, opacity: 0.95 }),
          );
          ring.lookAt(new THREE.Vector3(0, 0, 1));
          group.add(ring);
          const marker = makeYouAreHereSprite();
          if (marker) group.add(marker);
        }

        const nodeText = node?.text || "";
        const hashBase = String(node.id || nodeText).length + nodeText.length;
        const shouldShowLabel =
          debugMode ||
          node.id === selectedNodeId ||
          node.id === yourInsightNodeId ||
          supporterIds.has(node.id) ||
          challengerIds.has(node.id) ||
          hashBase % labelModulo === 0;

        if (shouldShowLabel) {
          const debugLines = debugMode && (node.level1 || node.level2 || node.level3)
            ? [`L1: ${node.level1 || "—"}`, `L2: ${node.level2 || "—"}`, `L3: ${node.level3 || "—"}`]
            : null;
          const label = makeNodeLabelSprite(nodeText, zoomTier, debugLines);
          if (label) {
            label.position.set(0, (node.id === yourInsightNodeId ? 18 : 11), 0);
            group.add(label);
          }
        }

        return group;
      }}
      nodeThreeObjectExtend={false}
      nodePositionUpdate={(obj, pos, node) => {
        const pos2 = floatingPosition(node, (typeof performance !== "undefined" ? performance.now() : Date.now()) / 1000);
        obj.position.set(pos2.x, pos2.y, pos2.z);
        return true;
      }}
      onNodeClick={onNodeClick}
      onBackgroundClick={onBackgroundClick}
      d3AlphaDecay={0.018}
      d3VelocityDecay={0.12}
      cooldownTicks={Infinity}
      cooldownTime={Infinity}
    />
  );
}
