"use client";
import { apiFetch } from '@/lib/api';

import React, { useState, useEffect, useRef, useCallback } from "react";
import {
  X,
  Search,
  RefreshCw,
  Loader2,
  ZoomIn,
  ZoomOut,
  Maximize2,
  Filter,
  Download,
  Info,
  GitBranch,
} from "lucide-react";
import { apiUrl } from "@/lib/api";
import { useTranslation } from "react-i18next";

// Cytoscape types - dynamic import at runtime, types only for TS
import type cytoscape from "cytoscape";
import type { EventObject } from "cytoscape";

interface GraphNode {
  id: string;
  label: string;
  entity_type: string;
  description: string;
  source_doc: string;
}

interface GraphEdge {
  source: string;
  target: string;
  label: string;
  keywords: string;
  weight: number;
}

interface GraphStats {
  total_nodes: number;
  total_edges: number;
  displayed_nodes: number;
  displayed_edges: number;
  entity_types: string[];
}

interface GraphData {
  kb_name: string;
  has_graph: boolean;
  nodes: GraphNode[];
  edges: GraphEdge[];
  stats: GraphStats;
  message?: string;
}

interface KnowledgeGraphViewerProps {
  kbName: string;
  open: boolean;
  onClose: () => void;
}

// Color palette for entity types
const ENTITY_TYPE_COLORS: Record<string, string> = {
  person: "#3B82F6",       // blue
  organization: "#8B5CF6", // purple
  concept: "#10B981",      // emerald
  location: "#F59E0B",     // amber
  event: "#EF4444",        // red
  artifact: "#EC4899",     // pink
  technology: "#06B6D4",   // cyan
  category: "#84CC16",     // lime
  geo: "#F97316",          // orange
  unknown: "#6B7280",      // gray
};

function getEntityColor(entityType: string): string {
  return ENTITY_TYPE_COLORS[entityType.toLowerCase()] || ENTITY_TYPE_COLORS.unknown;
}

export default function KnowledgeGraphViewer({
  kbName,
  open,
  onClose,
}: KnowledgeGraphViewerProps) {
  const { t } = useTranslation();
  const cyContainerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<cytoscape.Core | null>(null);

  const [graphData, setGraphData] = useState<GraphData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [selectedEdge, setSelectedEdge] = useState<GraphEdge | null>(null);
  const [filterType, setFilterType] = useState<string>("");
  const [nodeLimit, setNodeLimit] = useState(300);
  const [showFilters, setShowFilters] = useState(false);
  const [layoutRunning, setLayoutRunning] = useState(false);

  // Fetch graph data from API
  const fetchGraphData = useCallback((search?: string, entityType?: string): Promise<GraphData | null> => {
    const params = new URLSearchParams({ limit: nodeLimit.toString() });
    if (search) params.append("search", search);
    if (entityType) params.append("entity_type", entityType);
    return apiFetch(apiUrl(`/api/v1/knowledge/${encodeURIComponent(kbName)}/graph?${params}`))
      .then(response => { if (!response.ok) throw new Error(`Graph HTTP ${response.status}`); return response.json(); })
      .then((data: GraphData) => { setError(null); setGraphData(data); return data; })
      .catch(error => { setError(error instanceof Error ? error.message : "Could not load graph"); return null; })
      .finally(() => setLoading(false));
  }, [kbName, nodeLimit]);

  // Run force-directed layout
  const runLayout = useCallback((cy?: cytoscape.Core) => {
    const instance = cy || cyRef.current;
    if (!instance) return;

    setLayoutRunning(true);

    const layout = instance.layout({
      name: "cose",
      animate: true,
      animationDuration: 1500,
      randomize: true,
      nodeRepulsion: () => 8000,
      idealEdgeLength: () => 120,
      edgeElasticity: () => 100,
      gravity: 0.25,
      numIter: 500,
      padding: 50,
      componentSpacing: 80,
      nodeDimensionsIncludeLabels: true,
    } as cytoscape.CoseLayoutOptions);

    layout.on("layoutstop", () => {
      setLayoutRunning(false);
    });

    layout.run();
  }, []);


  // Initialize Cytoscape when data is loaded
  const initCytoscape = useCallback(
    async (data: GraphData) => {
      if (!cyContainerRef.current || !data.has_graph || data.nodes.length === 0) return;

      // Dynamically import cytoscape (client-side only)
      const cytoscapeModule = await import("cytoscape");
      const cy = cytoscapeModule.default;

      // Destroy previous instance
      if (cyRef.current) {
        cyRef.current.destroy();
      }

      // Build elements
      const elements: cytoscape.ElementDefinition[] = [];

      // Add nodes
      for (const node of data.nodes) {
        elements.push({
          data: {
            id: node.id,
            label: node.label.length > 25 ? node.label.slice(0, 22) + "..." : node.label,
            fullLabel: node.label,
            entity_type: node.entity_type,
            description: node.description,
            source_doc: node.source_doc,
            color: getEntityColor(node.entity_type),
          },
        });
      }

      // Add edges
      for (let i = 0; i < data.edges.length; i++) {
        const edge = data.edges[i];
        elements.push({
          data: {
            id: `e${i}`,
            source: edge.source,
            target: edge.target,
            label: edge.label.length > 30 ? edge.label.slice(0, 27) + "..." : edge.label,
            fullLabel: edge.label,
            keywords: edge.keywords,
            weight: edge.weight,
          },
        });
      }

      const instance = cy({
        container: cyContainerRef.current,
        elements,
        style: [
          {
            selector: "node",
            style: {
              label: "data(label)",
              "background-color": "data(color)",
              "text-valign": "bottom" as const,
              "text-halign": "center" as const,
              "font-size": "10px",
              "text-margin-y": 5,
              color: "#374151",
              "text-outline-color": "#ffffff",
              "text-outline-width": 2,
              width: 28,
              height: 28,
              "border-width": 2,
              "border-color": "#ffffff",
              "border-opacity": 0.8,
            },
          },
          {
            selector: "node:selected",
            style: {
              "border-width": 4,
              "border-color": "#1D4ED8",
              width: 40,
              height: 40,
              "font-size": "12px",
              "font-weight": "bold" as unknown as number,
              "z-index": 999,
            },
          },
          {
            selector: "node.highlighted",
            style: {
              "border-width": 3,
              "border-color": "#F59E0B",
              width: 36,
              height: 36,
            },
          },
          {
            selector: "node.faded",
            style: {
              opacity: 0.15,
            },
          },
          {
            selector: "edge",
            style: {
              width: 1.5,
              "line-color": "#CBD5E1",
              "target-arrow-color": "#CBD5E1",
              "target-arrow-shape": "triangle" as const,
              "curve-style": "bezier" as const,
              opacity: 0.6,
              "font-size": "8px",
              color: "#94A3B8",
              "text-rotation": "autorotate" as const,
              "text-outline-color": "#ffffff",
              "text-outline-width": 1.5,
            },
          },
          {
            selector: "edge:selected",
            style: {
              width: 3,
              "line-color": "#3B82F6",
              "target-arrow-color": "#3B82F6",
              opacity: 1,
              label: "data(label)",
              "font-size": "9px",
              color: "#1E40AF",
              "z-index": 999,
            },
          },
          {
            selector: "edge.highlighted",
            style: {
              width: 2.5,
              "line-color": "#F59E0B",
              "target-arrow-color": "#F59E0B",
              opacity: 1,
              label: "data(label)",
            },
          },
          {
            selector: "edge.faded",
            style: {
              opacity: 0.05,
            },
          },
        ],
        layout: { name: "preset" }, // Will run layout separately
        minZoom: 0.1,
        maxZoom: 5,
        wheelSensitivity: 0.3,
      });

      // Event: tap on node
      instance.on("tap", "node", (evt: EventObject) => {
        const nodeData = evt.target.data();
        setSelectedNode({
          id: nodeData.id,
          label: nodeData.fullLabel,
          entity_type: nodeData.entity_type,
          description: nodeData.description,
          source_doc: nodeData.source_doc,
        });
        setSelectedEdge(null);

        // Highlight connected nodes and edges
        instance.elements().removeClass("highlighted faded");
        const tapped = evt.target;
        const neighborhood = tapped.neighborhood().add(tapped);
        instance.elements().addClass("faded");
        neighborhood.removeClass("faded").addClass("highlighted");
        tapped.removeClass("highlighted"); // Selected node uses :selected style
      });

      // Event: tap on edge
      instance.on("tap", "edge", (evt: EventObject) => {
        const edgeData = evt.target.data();
        setSelectedEdge({
          source: edgeData.source,
          target: edgeData.target,
          label: edgeData.fullLabel,
          keywords: edgeData.keywords,
          weight: edgeData.weight,
        });
        setSelectedNode(null);
      });

      // Event: tap on background to deselect
      instance.on("tap", (evt: EventObject) => {
        if (evt.target === instance) {
          setSelectedNode(null);
          setSelectedEdge(null);
          instance.elements().removeClass("highlighted faded");
        }
      });

      cyRef.current = instance;

      // Run layout
      runLayout(instance);
    },
    []
  );

  const [previousGraph, setPreviousGraph] = useState({ open, kbName });
  if (previousGraph.open !== open || previousGraph.kbName !== kbName) {
    setPreviousGraph({ open, kbName }); setSelectedNode(null); setSelectedEdge(null); setSearchQuery(""); setFilterType("");
  }

  // Fetch and render when modal opens
  useEffect(() => {
    if (open && kbName) {
      fetchGraphData().then((data: GraphData | null) => {
        if (data) {
          // Small delay to ensure container is rendered
          setTimeout(() => initCytoscape(data), 100);
        }
      });
    }

    return () => {
      if (cyRef.current) {
        cyRef.current.destroy();
        cyRef.current = null;
      }
    };
  }, [open, kbName, fetchGraphData, initCytoscape]);

  // Zoom controls
  const handleZoomIn = () => cyRef.current?.zoom(cyRef.current.zoom() * 1.3);
  const handleZoomOut = () => cyRef.current?.zoom(cyRef.current.zoom() / 1.3);
  const handleFit = () => cyRef.current?.fit(undefined, 50);

  // Search handler
  const handleSearch = async () => {
    const data = await fetchGraphData(searchQuery, filterType);
    if (data) {
      setTimeout(() => initCytoscape(data), 100);
    }
  };

  // Export as PNG
  const handleExport = () => {
    if (!cyRef.current) return;
    const png = cyRef.current.png({ full: true, scale: 2, bg: "#ffffff" });
    const link = document.createElement("a");
    link.href = png;
    link.download = `${kbName}_knowledge_graph.png`;
    link.click();
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/50 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Modal */}
      <div className="relative bg-white dark:bg-slate-800 rounded-2xl shadow-2xl w-full max-w-[95vw] h-[90vh] flex flex-col overflow-hidden animate-in zoom-in-95">
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-slate-200 dark:border-slate-700">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-indigo-100 dark:bg-indigo-900/50 flex items-center justify-center">
              <GitBranch className="w-5 h-5 text-indigo-600 dark:text-indigo-400" />
            </div>
            <div>
              <h2 className="text-lg font-bold text-slate-900 dark:text-white">
                {t("Knowledge Graph")} - {kbName}
              </h2>
              {graphData?.stats && (
                <p className="text-xs text-slate-500 dark:text-slate-400">
                  {graphData.stats.displayed_nodes} / {graphData.stats.total_nodes}{" "}
                  {t("entities")} • {graphData.stats.displayed_edges} /{" "}
                  {graphData.stats.total_edges} {t("relations")}
                </p>
              )}
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-2 hover:bg-slate-100 dark:hover:bg-slate-700 rounded-lg transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Toolbar */}
        <div className="flex items-center gap-2 p-3 border-b border-slate-200 dark:border-slate-700 bg-slate-50/50 dark:bg-slate-800/50">
          {/* Search */}
          <div className="flex-1 relative max-w-md">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
            <input
              type="text"
              placeholder={t("Search entities...")}
              value={searchQuery}
              onChange={(e: React.ChangeEvent<HTMLInputElement>) => setSearchQuery(e.target.value)}
              onKeyDown={(e: React.KeyboardEvent<HTMLInputElement>) => e.key === "Enter" && handleSearch()}
              className="w-full pl-10 pr-4 py-2 rounded-lg border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-700 text-sm text-slate-800 dark:text-white"
            />
          </div>
          <button
            onClick={handleSearch}
            className="px-3 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 text-sm flex items-center gap-1.5"
          >
            <Search className="w-3.5 h-3.5" />
            {t("Search")}
          </button>

          <div className="w-px h-6 bg-slate-300 dark:bg-slate-600 mx-1" />

          {/* Filter toggle */}
          <button
            onClick={() => setShowFilters(!showFilters)}
            className={`p-2 rounded-lg text-sm transition-colors ${
              showFilters || filterType
                ? "bg-indigo-100 dark:bg-indigo-900/40 text-indigo-600 dark:text-indigo-400"
                : "hover:bg-slate-200 dark:hover:bg-slate-600 text-slate-600 dark:text-slate-400"
            }`}
            title={t("Filter by type")}
          >
            <Filter className="w-4 h-4" />
          </button>

          {/* Zoom controls */}
          <button
            onClick={handleZoomIn}
            className="p-2 hover:bg-slate-200 dark:hover:bg-slate-600 rounded-lg text-slate-600 dark:text-slate-400"
            title={t("Zoom in")}
          >
            <ZoomIn className="w-4 h-4" />
          </button>
          <button
            onClick={handleZoomOut}
            className="p-2 hover:bg-slate-200 dark:hover:bg-slate-600 rounded-lg text-slate-600 dark:text-slate-400"
            title={t("Zoom out")}
          >
            <ZoomOut className="w-4 h-4" />
          </button>
          <button
            onClick={handleFit}
            className="p-2 hover:bg-slate-200 dark:hover:bg-slate-600 rounded-lg text-slate-600 dark:text-slate-400"
            title={t("Fit to view")}
          >
            <Maximize2 className="w-4 h-4" />
          </button>

          {/* Re-layout */}
          <button
            onClick={() => runLayout()}
            disabled={layoutRunning}
            className="p-2 hover:bg-slate-200 dark:hover:bg-slate-600 rounded-lg text-slate-600 dark:text-slate-400 disabled:opacity-50"
            title={t("Re-layout")}
          >
            <RefreshCw className={`w-4 h-4 ${layoutRunning ? "animate-spin" : ""}`} />
          </button>

          {/* Export */}
          <button
            onClick={handleExport}
            className="p-2 hover:bg-slate-200 dark:hover:bg-slate-600 rounded-lg text-slate-600 dark:text-slate-400"
            title={t("Export as PNG")}
          >
            <Download className="w-4 h-4" />
          </button>
        </div>

        {/* Filter bar */}
        {showFilters && graphData?.stats?.entity_types && (
          <div className="flex items-center gap-2 px-4 py-2 border-b border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/80 overflow-x-auto">
            <span className="text-xs font-medium text-slate-500 dark:text-slate-400 whitespace-nowrap">
              {t("Entity Type")}:
            </span>
            <button
              onClick={() => {
                setFilterType("");
                fetchGraphData(searchQuery, "").then((d) => d && setTimeout(() => initCytoscape(d), 100));
              }}
              className={`px-2.5 py-1 rounded-full text-xs font-medium transition-colors whitespace-nowrap ${
                !filterType
                  ? "bg-indigo-600 text-white"
                  : "bg-slate-200 dark:bg-slate-600 text-slate-700 dark:text-slate-300 hover:bg-slate-300"
              }`}
            >
              {t("All")} ({graphData.stats.total_nodes})
            </button>
            {graphData.stats.entity_types.map((type) => (
              <button
                key={type}
                onClick={() => {
                  setFilterType(type);
                  fetchGraphData(searchQuery, type).then(
                    (d) => d && setTimeout(() => initCytoscape(d), 100)
                  );
                }}
                className={`px-2.5 py-1 rounded-full text-xs font-medium transition-colors whitespace-nowrap flex items-center gap-1.5 ${
                  filterType === type
                    ? "text-white"
                    : "bg-slate-200 dark:bg-slate-600 text-slate-700 dark:text-slate-300 hover:bg-slate-300"
                }`}
                style={
                  filterType === type
                    ? { backgroundColor: getEntityColor(type) }
                    : {}
                }
              >
                <span
                  className="w-2 h-2 rounded-full inline-block"
                  style={{ backgroundColor: getEntityColor(type) }}
                />
                {type}
              </button>
            ))}
          </div>
        )}

        {/* Main content */}
        <div className="flex-1 flex overflow-hidden">
          {/* Graph container */}
          <div className="flex-1 relative">
            {loading && (
              <div className="absolute inset-0 flex items-center justify-center bg-white/80 dark:bg-slate-800/80 z-10">
                <div className="flex flex-col items-center gap-3">
                  <Loader2 className="w-10 h-10 animate-spin text-indigo-600" />
                  <p className="text-sm text-slate-600 dark:text-slate-400">
                    {t("Loading knowledge graph...")}
                  </p>
                </div>
              </div>
            )}

            {layoutRunning && (
              <div className="absolute top-3 left-3 z-10 bg-indigo-600 text-white px-3 py-1.5 rounded-full text-xs font-medium flex items-center gap-2 shadow-lg">
                <Loader2 className="w-3 h-3 animate-spin" />
                {t("Computing layout...")}
              </div>
            )}

            {error && (
              <div className="absolute inset-0 flex items-center justify-center">
                <div className="text-center p-6">
                  <p className="text-red-600 dark:text-red-400 font-medium">{error}</p>
                  <button
                    onClick={() => fetchGraphData()}
                    className="mt-3 px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm"
                  >
                    {t("Retry")}
                  </button>
                </div>
              </div>
            )}

            {graphData && !graphData.has_graph && !loading && (
              <div className="absolute inset-0 flex items-center justify-center">
                <div className="text-center p-6 max-w-md">
                  <GitBranch className="w-16 h-16 mx-auto mb-4 text-slate-300 dark:text-slate-600" />
                  <p className="text-slate-600 dark:text-slate-400 font-medium text-lg mb-2">
                    {t("No Knowledge Graph")}
                  </p>
                  <p className="text-slate-500 dark:text-slate-500 text-sm">
                    {graphData.message ||
                      t(
                        "This knowledge base does not have a graph RAG index. Try using LightRAG or RAGAnything provider."
                      )}
                  </p>
                </div>
              </div>
            )}

            {graphData && graphData.has_graph && graphData.nodes.length === 0 && !loading && (
              <div className="absolute inset-0 flex items-center justify-center">
                <div className="text-center p-6">
                  <Search className="w-12 h-12 mx-auto mb-3 text-slate-300" />
                  <p className="text-slate-500 dark:text-slate-400">
                    {t("No entities match your search/filter.")}
                  </p>
                </div>
              </div>
            )}

            {/* Cytoscape container */}
            <div
              ref={cyContainerRef}
              className="w-full h-full"
              style={{ minHeight: "400px" }}
            />

            {/* Legend */}
            {graphData?.has_graph && graphData.stats.entity_types.length > 0 && (
              <div className="absolute bottom-3 left-3 bg-white/90 dark:bg-slate-800/90 backdrop-blur-sm p-3 rounded-xl shadow-lg border border-slate-200 dark:border-slate-700 max-w-xs">
                <p className="text-[10px] font-bold text-slate-500 dark:text-slate-400 uppercase tracking-wider mb-2">
                  {t("Entity Types")}
                </p>
                <div className="flex flex-wrap gap-x-3 gap-y-1">
                  {graphData.stats.entity_types.map((type) => (
                    <div key={type} className="flex items-center gap-1.5">
                      <span
                        className="w-2.5 h-2.5 rounded-full"
                        style={{ backgroundColor: getEntityColor(type) }}
                      />
                      <span className="text-[11px] text-slate-600 dark:text-slate-400">
                        {type}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* Detail panel */}
          {(selectedNode || selectedEdge) && (
            <div className="w-80 border-l border-slate-200 dark:border-slate-700 overflow-y-auto bg-slate-50 dark:bg-slate-800/80 p-4">
              {selectedNode && (
                <div className="space-y-4">
                  <div className="flex items-start gap-3">
                    <div
                      className="w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0"
                      style={{ backgroundColor: getEntityColor(selectedNode.entity_type) + "20" }}
                    >
                      <div
                        className="w-3 h-3 rounded-full"
                        style={{ backgroundColor: getEntityColor(selectedNode.entity_type) }}
                      />
                    </div>
                    <div>
                      <h3 className="font-bold text-slate-900 dark:text-white text-sm">
                        {selectedNode.label}
                      </h3>
                      <span
                        className="inline-block px-2 py-0.5 rounded-full text-[10px] font-bold uppercase text-white mt-1"
                        style={{ backgroundColor: getEntityColor(selectedNode.entity_type) }}
                      >
                        {selectedNode.entity_type}
                      </span>
                    </div>
                  </div>

                  {selectedNode.description && (
                    <div>
                      <label className="text-[10px] font-bold text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                        {t("Description")}
                      </label>
                      <p className="text-sm text-slate-700 dark:text-slate-300 mt-1 leading-relaxed">
                        {selectedNode.description}
                      </p>
                    </div>
                  )}

                  {selectedNode.source_doc && (
                    <div>
                      <label className="text-[10px] font-bold text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                        {t("Source Document")}
                      </label>
                      <p className="text-xs text-slate-600 dark:text-slate-400 mt-1 bg-white dark:bg-slate-700 p-2 rounded-lg">
                        {selectedNode.source_doc}
                      </p>
                    </div>
                  )}

                  <div>
                    <label className="text-[10px] font-bold text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                      {t("Entity ID")}
                    </label>
                    <p className="text-xs font-mono text-slate-600 dark:text-slate-400 mt-1 bg-white dark:bg-slate-700 p-2 rounded-lg break-all">
                      {selectedNode.id}
                    </p>
                  </div>
                </div>
              )}

              {selectedEdge && (
                <div className="space-y-4">
                  <div className="flex items-center gap-2">
                    <Info className="w-5 h-5 text-blue-500" />
                    <h3 className="font-bold text-slate-900 dark:text-white text-sm">
                      {t("Relationship")}
                    </h3>
                  </div>

                  <div className="bg-white dark:bg-slate-700 p-3 rounded-xl space-y-2">
                    <div className="flex items-center gap-2 text-sm">
                      <span className="px-2 py-0.5 bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300 rounded font-medium text-xs">
                        {selectedEdge.source}
                      </span>
                      <span className="text-slate-400">→</span>
                      <span className="px-2 py-0.5 bg-emerald-100 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-300 rounded font-medium text-xs">
                        {selectedEdge.target}
                      </span>
                    </div>
                  </div>

                  {selectedEdge.label && (
                    <div>
                      <label className="text-[10px] font-bold text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                        {t("Description")}
                      </label>
                      <p className="text-sm text-slate-700 dark:text-slate-300 mt-1 leading-relaxed">
                        {selectedEdge.label}
                      </p>
                    </div>
                  )}

                  {selectedEdge.keywords && (
                    <div>
                      <label className="text-[10px] font-bold text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                        {t("Keywords")}
                      </label>
                      <p className="text-xs text-slate-600 dark:text-slate-400 mt-1">
                        {selectedEdge.keywords}
                      </p>
                    </div>
                  )}

                  <div>
                    <label className="text-[10px] font-bold text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                      {t("Weight")}
                    </label>
                    <div className="flex items-center gap-2 mt-1">
                      <div className="flex-1 bg-slate-200 dark:bg-slate-600 rounded-full h-2">
                        <div
                          className="bg-indigo-500 rounded-full h-2"
                          style={{
                            width: `${Math.min(100, selectedEdge.weight * 10)}%`,
                          }}
                        />
                      </div>
                      <span className="text-xs font-mono text-slate-600 dark:text-slate-400">
                        {selectedEdge.weight.toFixed(1)}
                      </span>
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
