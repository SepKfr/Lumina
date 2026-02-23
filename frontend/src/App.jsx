import React, { useEffect, useRef, useState } from "react";
import { fetchGraph, submitInsight } from "./api";
import ChatPanel from "./components/ChatPanel";
import InsightForm from "./components/InsightForm";
import Map3D from "./components/Map3D";
import SidePanel from "./components/SidePanel";

function isOpposing(a, b) {
  return (a === "pro" && b === "con") || (a === "con" && b === "pro");
}

function normalizeIdeaText(text) {
  return (text || "").trim().toLowerCase().replace(/\s+/g, " ");
}

function dedupeAndSeparate(supportersInput, challengersInput, seedText = "") {
  const supporters = [];
  const challengers = [];
  const supporterKeys = new Set(seedText ? [normalizeIdeaText(seedText)] : []);
  const challengerKeys = new Set();

  for (const s of supportersInput || []) {
    const key = normalizeIdeaText(s.text);
    if (!key || supporterKeys.has(key)) continue;
    supporterKeys.add(key);
    supporters.push(s);
  }

  for (const c of challengersInput || []) {
    const key = normalizeIdeaText(c.text);
    if (!key || supporterKeys.has(key) || challengerKeys.has(key)) continue;
    challengerKeys.add(key);
    challengers.push(c);
  }

  return { supporters: supporters.slice(0, 6), challengers: challengers.slice(0, 6) };
}

export default function App() {
  const graphRef = useRef(null);
  const mapWrapRef = useRef(null);
  const zoomTierRef = useRef("mid");
  const zoomDebounceRef = useRef(null);
  const [graph, setGraph] = useState({ nodes: [], edges: [] });
  const [mapSize, setMapSize] = useState({ width: 900, height: 600 });
  const [zoomTier, setZoomTier] = useState("mid");
  const [selectedNode, setSelectedNode] = useState(null);
  const [yourInsightNode, setYourInsightNode] = useState(null); // persists after submit until panel closed
  const [selectionContext, setSelectionContext] = useState("graph");
  const [supporters, setSupporters] = useState([]);
  const [clusters, setClusters] = useState({}); // cluster_id -> { title, summary }
  const [challengers, setChallengers] = useState([]);
  const [chatMode, setChatMode] = useState("support");
  const [counterpartyBelief, setCounterpartyBelief] = useState(null);
  const [chatOpen, setChatOpen] = useState(false);
  const [conversation, setConversation] = useState([]);

  async function loadGraph() {
    const data = await fetchGraph({ budget: 120 });
    setGraph(data);
    setClusters(data.clusters || {});
  }

  useEffect(() => {
    loadGraph().catch(() => null);
  }, []);

  useEffect(() => {
    if (!selectedNode) return undefined;
    const fg = graphRef.current;
    const controls = fg?.controls?.();
    if (!controls) return undefined;

    const nodeId = String(selectedNode.id);
    const tierForDistance = (distance) => {
      if (distance < 150) return { key: "near", depth: 3, budget: 220 };
      if (distance < 320) return { key: "mid", depth: 2, budget: 120 };
      return { key: "far", depth: 1, budget: 70 };
    };

    const onZoomChange = () => {
      if (zoomDebounceRef.current) clearTimeout(zoomDebounceRef.current);
      zoomDebounceRef.current = setTimeout(async () => {
        const cam = fg.camera?.();
        if (!cam) return;
        const tier = tierForDistance(cam.position.length());
        if (tier.key === zoomTierRef.current) return;
        zoomTierRef.current = tier.key;
        setZoomTier(tier.key);

        try {
          const sub = await fetchGraph({ node_id: nodeId, depth: tier.depth, budget: tier.budget });
          const subNodes = sub.nodes || [];
          const subEdges = sub.edges || [];
          setClusters(sub.clusters || {});

          if (selectionContext === "submission") {
            const topicNodes = subNodes.filter((n) => n.cluster_id === selectedNode.cluster_id || String(n.id) === nodeId);
            const topicNodeIds = new Set(topicNodes.map((n) => String(n.id)));
            const topicEdges = subEdges.filter((e) => topicNodeIds.has(String(e.src)) && topicNodeIds.has(String(e.dst)));
            setGraph({ nodes: topicNodes, edges: topicEdges });
          } else {
            setGraph({ nodes: subNodes, edges: subEdges });
          }
        } catch {
          // Keep current view if zoom-detail fetch fails.
        }
      }, 220);
    };

    controls.addEventListener?.("change", onZoomChange);
    return () => {
      controls.removeEventListener?.("change", onZoomChange);
      if (zoomDebounceRef.current) clearTimeout(zoomDebounceRef.current);
    };
  }, [selectedNode, selectionContext]);

  useEffect(() => {
    function updateMapSize() {
      if (!mapWrapRef.current) return;
      const rect = mapWrapRef.current.getBoundingClientRect();
      setMapSize({
        width: Math.max(320, Math.floor(rect.width)),
        height: Math.max(320, Math.floor(rect.height)),
      });
    }
    updateMapSize();
    window.addEventListener("resize", updateMapSize);
    return () => window.removeEventListener("resize", updateMapSize);
  }, []);

  async function handleNodeClick(node) {
    setSelectedNode(node);
    setSelectionContext("graph");
    zoomTierRef.current = "mid";
    setZoomTier("mid");
    const nodeId = typeof node.id === "string" ? node.id : (node.id?.toString?.() ?? node.id);
    const sub = await fetchGraph({ node_id: nodeId, depth: 2, budget: 80 });
    const subNodes = sub.nodes || [];
    const subEdges = sub.edges || [];
    setClusters(sub.clusters || {});

    // If API returned only one node (no neighbors in DB), keep current graph so we don't collapse to a single node
    const useCurrentGraph =
      subNodes.length <= 1 &&
      (subEdges || []).length === 0 &&
      graph.nodes?.length > 1;
    const nodes = useCurrentGraph ? graph.nodes : subNodes;
    const edges = useCurrentGraph ? graph.edges : subEdges;

    let finalNodes = nodes;
    if (!useCurrentGraph && yourInsightNode && !nodes.some((n) => String(n.id) === String(yourInsightNode.id))) {
      finalNodes = [...nodes, yourInsightNode];
    }
    setGraph({ nodes: finalNodes, edges });
    const neighborIds = new Set();
    for (const e of edges || []) {
      if (String(e.src) === String(node.id)) neighborIds.add(String(e.dst));
      if (String(e.dst) === String(node.id)) neighborIds.add(String(e.src));
    }
    const neighbors = (finalNodes || [])
      .filter((n) => neighborIds.has(String(n.id)))
      .sort((a, b) => {
        const edgeA = (edges || []).find((e) => (String(e.src) === String(node.id) && String(e.dst) === String(a.id)) || (String(e.dst) === String(node.id) && String(e.src) === String(a.id)));
        const edgeB = (edges || []).find((e) => (String(e.src) === String(node.id) && String(e.dst) === String(b.id)) || (String(e.dst) === String(node.id) && String(e.src) === String(b.id)));
        const aWeight = edgeA?.weight ?? 0;
        const bWeight = edgeB?.weight ?? 0;
        return bWeight - aWeight;
      })
      .slice(0, 14);
    const split = dedupeAndSeparate(
      neighbors.filter((n) => n.stance_label === node.stance_label),
      neighbors.filter((n) => isOpposing(node.stance_label, n.stance_label)),
      node.text,
    );
    setSupporters(split.supporters);
    setChallengers(split.challengers);

    // Auto-zoom into the clicked node's connected neighborhood.
    const fg = graphRef.current;
    if (fg && fg.zoomToFit) {
      setTimeout(() => {
        try {
          const connectedIds = new Set([String(node.id)]);
          for (const e of edges || []) {
            if (String(e.src) === String(node.id)) connectedIds.add(String(e.dst));
            if (String(e.dst) === String(node.id)) connectedIds.add(String(e.src));
          }
          fg.zoomToFit(700, 40, (n) => connectedIds.has(String(n.id)));
        } catch {
          // no-op: keep current camera if zoom-to-fit is unavailable
        }
      }, 120);
    }
  }

  async function handleSubmitInsight(text) {
    const result = await submitInsight(text);
    setYourInsightNode(result.node);
    // Focus the map around the newly added idea so users see "where they are"
    const focused = await fetchGraph({ node_id: result.node.id, depth: 2, budget: 120 });
    const topicNodes = (focused.nodes || []).filter((n) => n.cluster_id === result.node.cluster_id || n.id === result.node.id);
    const topicNodeIds = new Set(topicNodes.map((n) => n.id));
    const topicEdges = (focused.edges || []).filter((e) => topicNodeIds.has(e.src) && topicNodeIds.has(e.dst));
    setGraph({ nodes: topicNodes, edges: topicEdges });
    setClusters(focused.clusters || {});
    if (result.cluster) {
      setClusters((prev) => ({ ...prev, [result.node.cluster_id]: { title: result.cluster.title, summary: result.cluster.summary } }));
    }
    setSelectedNode(result.node);
    setSelectionContext("submission");
    zoomTierRef.current = "mid";
    setZoomTier("mid");
    const split = dedupeAndSeparate(result.supporters || [], result.challengers || [], result.node?.text || "");
    setSupporters(split.supporters);
    setChallengers(split.challengers);

    const fg = graphRef.current;
    if (fg && fg.cameraPosition) {
      fg.cameraPosition({ x: 0, y: 0, z: 240 }, { x: 0, y: 0, z: 0 }, 800);
    }
  }

  function openChat(mode, counterpartyBelief = null) {
    if (!selectedNode) return;
    setChatMode(mode);
    setCounterpartyBelief(counterpartyBelief);
    setConversation([]);
    setChatOpen(true);
  }

  function closePanel() {
    setSelectedNode(null);
    setYourInsightNode(null);
    setSelectionContext("graph");
    setSupporters([]);
    setChallengers([]);
    loadGraph().catch(() => null);
  }

  function focusOnYourInsight() {
    if (!yourInsightNode) return;
    setSelectedNode(yourInsightNode);
    setSelectionContext("submission");
    const neighbors = (graph.edges || [])
      .filter((e) => e.src === yourInsightNode.id || e.dst === yourInsightNode.id)
      .slice(0, 14);
    const neighborIds = new Set([yourInsightNode.id]);
    neighbors.forEach((e) => {
      neighborIds.add(e.src);
      neighborIds.add(e.dst);
    });
    const neighborNodes = (graph.nodes || []).filter((n) => neighborIds.has(n.id));
    const split = dedupeAndSeparate(
      neighborNodes.filter((n) => n.id !== yourInsightNode.id && n.cluster_id === yourInsightNode.cluster_id && n.stance_label === yourInsightNode.stance_label),
      neighborNodes.filter((n) => n.cluster_id === yourInsightNode.cluster_id && isOpposing(yourInsightNode.stance_label, n.stance_label)),
      yourInsightNode.text,
    );
    setSupporters(split.supporters);
    setChallengers(split.challengers);
    const fg = graphRef.current;
    if (fg && fg.zoomToFit) {
      setTimeout(() => {
        try {
          fg.zoomToFit(500, 40, (n) => n.id === yourInsightNode.id);
        } catch (_) {}
      }, 100);
    }
  }

  function zoomIntoMapArea(event) {
    const fg = graphRef.current;
    if (!fg?.renderer) return;
    const renderer = fg.renderer();
    const dom = renderer?.domElement;
    if (!dom) return;
    const controls = fg.controls?.();
    if (!controls) return;

    let x;
    let y;
    if (typeof event?.clientX === "number" && typeof event?.clientY === "number") {
      const rect = dom.getBoundingClientRect();
      x = event.clientX - rect.left;
      y = event.clientY - rect.top;
    } else if (typeof event?.offsetX === "number" && typeof event?.offsetY === "number") {
      x = event.offsetX;
      y = event.offsetY;
    } else {
      // Fallback: zoom toward center if event coords are unavailable.
      x = dom.clientWidth / 2;
      y = dom.clientHeight / 2;
    }

    let target = { x: 0, y: 0, z: 0 };
    if (fg.screen2GraphCoords) {
      try {
        target = fg.screen2GraphCoords(x, y, 0);
      } catch {
        target = { x: 0, y: 0, z: 0 };
      }
    }
    controls.target?.set?.(target.x, target.y, target.z);
    if (typeof controls.dollyIn === "function") {
      controls.dollyIn(1.35);
      controls.update?.();
      return;
    }
    // Fallback for control variants without dollyIn.
    const cam = fg.camera?.();
    if (!cam || !fg.cameraPosition) return;
    fg.cameraPosition(
      {
        x: cam.position.x + (target.x - cam.position.x) * 0.45,
        y: cam.position.y + (target.y - cam.position.y) * 0.45,
        z: Math.max(12, cam.position.z + (target.z - cam.position.z) * 0.45),
      },
      target,
      500,
    );
  }

  return (
    <div className="app">
      <header>
        <h1>Lumina</h1>
        <InsightForm onSubmit={handleSubmitInsight} />
      </header>
      <main className={selectedNode ? "with-panel" : ""}>
        <div className="map-wrap" ref={mapWrapRef}>
          <Map3D
            graph={graph}
            selectedNodeId={selectedNode?.id}
            yourInsightNodeId={yourInsightNode?.id}
            zoomTier={zoomTier}
            supporters={supporters}
            challengers={challengers}
            onNodeClick={handleNodeClick}
            onBackgroundClick={zoomIntoMapArea}
            graphRef={graphRef}
            width={mapSize.width}
            height={mapSize.height}
          />
          {!selectedNode && (
            <div className="map-overlay-tip">
              Click a node for details and chat. Click empty map area to zoom toward that region.
            </div>
          )}
        </div>
        {selectedNode && (
          <SidePanel
            node={selectedNode}
            yourInsightNode={yourInsightNode}
            selectionContext={selectionContext}
            supporters={supporters}
            challengers={challengers}
            onOpenChat={openChat}
            onClose={closePanel}
            onFocusYourInsight={focusOnYourInsight}
          />
        )}
      </main>
      <ChatPanel
        visible={chatOpen}
        mode={chatMode}
        seedNode={selectedNode}
        userBelief={yourInsightNode?.text || selectedNode?.text || ""}
        counterpartyBelief={counterpartyBelief}
        conversation={conversation}
        setConversation={setConversation}
        onClose={() => setChatOpen(false)}
      />
    </div>
  );
}
