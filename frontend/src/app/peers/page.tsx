"use client";

import { useState, useEffect, useCallback } from "react";
import {
  Users,
  Wifi,
  WifiOff,
  Globe,
  Shield,
  RefreshCw,
  Copy,
  Check,
  Activity,
  Plus,
  Square,
  Clock,
  Server,
} from "lucide-react";
import { useSSE, SSEEvent } from "@/hooks/useSSE";
import {
  fetchNetworkStatus,
  fetchSecurityStatus,
  getStreamPeersUrl,
  NetworkStatus,
  SecurityStatus,
  SpawnedNode,
  spawnNodes,
  fetchSpawnedNodes,
  stopNode,
} from "@/lib/api";

interface PeerInfo {
  peer_id: string;
  peer_id_full: string;
  multiaddrs: string[];
  latency_ms: number | null;
}

interface PeersUpdate {
  running: boolean;
  peer_id?: string;
  peer_count: number;
  peers: PeerInfo[];
  timestamp: number;
}

export default function PeersPage() {
  const [networkStatus, setNetworkStatus] = useState<NetworkStatus | null>(null);
  const [securityStatus, setSecurityStatus] = useState<SecurityStatus | null>(null);
  const [peersData, setPeersData] = useState<PeersUpdate | null>(null);
  const [copied, setCopied] = useState(false);
  const [loading, setLoading] = useState(true);

  // Node orchestration state
  const [spawnedNodes, setSpawnedNodes] = useState<SpawnedNode[]>([]);
  const [spawnCount, setSpawnCount] = useState(1);
  const [spawning, setSpawning] = useState(false);
  const [stoppingId, setStoppingId] = useState<string | null>(null);
  const [orchError, setOrchError] = useState<string | null>(null);

  const loadSpawnedNodes = useCallback(async () => {
    try {
      const res = await fetchSpawnedNodes();
      setSpawnedNodes(res.nodes);
    } catch {
      // orchestration may be disabled — silently ignore
    }
  }, []);

  // Fetch initial status
  useEffect(() => {
    async function fetchStatus() {
      try {
        const [network, security] = await Promise.all([
          fetchNetworkStatus(),
          fetchSecurityStatus(),
        ]);
        setNetworkStatus(network);
        setSecurityStatus(security);
      } catch (err) {
        console.error("Failed to fetch status:", err);
      } finally {
        setLoading(false);
      }
    }
    fetchStatus();
    loadSpawnedNodes();
  }, [loadSpawnedNodes]);

  // Poll spawned node statuses every 10s
  useEffect(() => {
    const id = setInterval(loadSpawnedNodes, 10_000);
    return () => clearInterval(id);
  }, [loadSpawnedNodes]);

  const handleSpawn = useCallback(async () => {
    setSpawning(true);
    setOrchError(null);
    try {
      await spawnNodes(spawnCount);
      await loadSpawnedNodes();
    } catch (err) {
      setOrchError(err instanceof Error ? err.message : String(err));
    } finally {
      setSpawning(false);
    }
  }, [spawnCount, loadSpawnedNodes]);

  const handleStop = useCallback(async (nodeId: string) => {
    setStoppingId(nodeId);
    setOrchError(null);
    try {
      await stopNode(nodeId);
      await loadSpawnedNodes();
    } catch (err) {
      setOrchError(err instanceof Error ? err.message : String(err));
    } finally {
      setStoppingId(null);
    }
  }, [loadSpawnedNodes]);

  // SSE for real-time peer updates
  const handlePeerEvent = useCallback((event: SSEEvent) => {
    if (event.event === "peers") {
      setPeersData(event.data as PeersUpdate);
    }
  }, []);

  const { connected, error, reconnect } = useSSE({
    url: getStreamPeersUrl(5),
    enabled: true,
    onEvent: handlePeerEvent,
  });

  const copyPeerId = useCallback(() => {
    if (networkStatus?.peer_id) {
      navigator.clipboard.writeText(networkStatus.peer_id);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  }, [networkStatus]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <RefreshCw className="animate-spin text-aura-primary" size={32} />
      </div>
    );
  }

  const isRunning = networkStatus?.running ?? false;
  const peerCount = peersData?.peer_count ?? networkStatus?.peers ?? 0;

  return (
    <div className="max-w-5xl mx-auto">
      {/* Header */}
      <div className="text-center mb-8">
        <h1 className="text-3xl font-bold text-white mb-2">
          <Users className="inline-block mr-2 text-aura-accent" size={32} />
          P2P Network
        </h1>
        <p className="text-slate-400">
          Monitor your connection to the federated knowledge mesh
        </p>
      </div>

      {/* Status Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
        {/* Connection Status */}
        <div className="bg-slate-800 rounded-xl border border-slate-700 p-6">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-sm font-medium text-slate-400">Network Status</h3>
            {isRunning ? (
              <Wifi className="text-green-400" size={20} />
            ) : (
              <WifiOff className="text-red-400" size={20} />
            )}
          </div>
          <div className="flex items-baseline gap-2">
            <span className={`text-2xl font-bold ${isRunning ? "text-green-400" : "text-red-400"}`}>
              {isRunning ? "Connected" : "Offline"}
            </span>
          </div>
          <div className="mt-2 flex items-center gap-2 text-sm text-slate-500">
            <Activity size={14} className={connected ? "text-green-400" : "text-slate-500"} />
            {connected ? "Live updates" : "Reconnecting..."}
          </div>
        </div>

        {/* Peer Count */}
        <div className="bg-slate-800 rounded-xl border border-slate-700 p-6">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-sm font-medium text-slate-400">Connected Peers</h3>
            <Users className="text-aura-primary" size={20} />
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-4xl font-bold text-white">{peerCount}</span>
            <span className="text-slate-400">nodes</span>
          </div>
          {networkStatus?.mdns_enabled && (
            <div className="mt-2 text-sm text-slate-500">
              mDNS discovery enabled
            </div>
          )}
        </div>

        {/* Security Status */}
        <div className="bg-slate-800 rounded-xl border border-slate-700 p-6">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-sm font-medium text-slate-400">Security</h3>
            <Shield className={securityStatus?.did_active ? "text-green-400" : "text-slate-500"} size={20} />
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-2xl font-bold text-white">
              {securityStatus?.did_active ? "DID Active" : "No DID"}
            </span>
          </div>
          <div className="mt-2 text-sm text-slate-500">
            {securityStatus?.auth_proof_type || "—"}
          </div>
        </div>
      </div>

      {/* This Node Info */}
      <div className="bg-slate-800 rounded-xl border border-slate-700 p-6 mb-8">
        <h2 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
          <Globe size={18} className="text-aura-accent" />
          This Node
        </h2>

        <div className="space-y-4">
          <div>
            <label className="text-sm text-slate-400 block mb-1">Peer ID</label>
            <div className="flex items-center gap-2">
              <code className="flex-1 bg-slate-900 px-4 py-2 rounded-lg text-sm text-aura-accent font-mono truncate">
                {networkStatus?.peer_id || "Not available"}
              </code>
              <button
                onClick={copyPeerId}
                className="px-3 py-2 bg-slate-700 hover:bg-slate-600 rounded-lg transition-colors"
                disabled={!networkStatus?.peer_id}
              >
                {copied ? <Check size={16} className="text-green-400" /> : <Copy size={16} />}
              </button>
            </div>
          </div>

          <div>
            <label className="text-sm text-slate-400 block mb-1">Multiaddr</label>
            <code className="block bg-slate-900 px-4 py-2 rounded-lg text-sm text-slate-300 font-mono truncate">
              {networkStatus?.multiaddr || "Not available"}
            </code>
          </div>

          {securityStatus?.did && (
            <div>
              <label className="text-sm text-slate-400 block mb-1">DID</label>
              <code className="block bg-slate-900 px-4 py-2 rounded-lg text-sm text-slate-300 font-mono truncate">
                {securityStatus.did}
              </code>
            </div>
          )}
        </div>
      </div>

      {/* Connected Peers List */}
      <div className="bg-slate-800 rounded-xl border border-slate-700 p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-white flex items-center gap-2">
            <Users size={18} className="text-aura-secondary" />
            Connected Peers
          </h2>
          <button
            onClick={reconnect}
            className="text-sm text-slate-400 hover:text-white flex items-center gap-1 transition-colors"
          >
            <RefreshCw size={14} />
            Refresh
          </button>
        </div>

        {peersData?.peers && peersData.peers.length > 0 ? (
          <div className="space-y-3">
            {peersData.peers.map((peer, i) => (
              <div
                key={peer.peer_id_full || i}
                className="bg-slate-700/50 rounded-lg p-4 border border-slate-600"
              >
                <div className="flex items-start justify-between">
                  <div className="flex items-center gap-3">
                    <div className="w-3 h-3 rounded-full bg-green-400 peer-pulse" />
                    <div>
                      <code className="text-sm text-aura-accent font-mono">
                        {peer.peer_id}
                      </code>
                      {peer.latency_ms !== null && (
                        <span className="ml-2 text-xs text-slate-500">
                          {peer.latency_ms}ms
                        </span>
                      )}
                    </div>
                  </div>
                </div>
                {peer.multiaddrs && peer.multiaddrs.length > 0 && (
                  <div className="mt-2 text-xs text-slate-500 font-mono">
                    {peer.multiaddrs[0]}
                  </div>
                )}
              </div>
            ))}
          </div>
        ) : (
          <div className="text-center py-8 text-slate-500">
            <Users size={32} className="mx-auto mb-2 text-slate-600" />
            <p>No peers connected</p>
            <p className="text-sm mt-1">
              Waiting for peers to join the mesh...
            </p>
          </div>
        )}
      </div>

      {/* Node Orchestration */}
      <div className="bg-slate-800 rounded-xl border border-slate-700 p-6 mt-8">
        <h2 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
          <Server size={18} className="text-aura-primary" />
          Node Orchestration
        </h2>

        {/* Spawn controls */}
        <div className="flex items-center gap-3 mb-6">
          <label className="text-sm text-slate-400 whitespace-nowrap">Spawn nodes:</label>
          <input
            type="number"
            min={1}
            max={10}
            value={spawnCount}
            onChange={(e) => setSpawnCount(Math.max(1, Math.min(10, Number(e.target.value))))}
            className="w-20 px-3 py-2 bg-slate-900 border border-slate-700 rounded-lg text-white text-sm focus:outline-none focus:ring-2 focus:ring-aura-primary"
            disabled={spawning}
          />
          <button
            onClick={handleSpawn}
            disabled={spawning}
            className="flex items-center gap-2 px-4 py-2 bg-aura-primary hover:bg-aura-primary/80 disabled:bg-slate-700 disabled:cursor-not-allowed rounded-lg text-white text-sm font-medium transition-colors"
          >
            {spawning ? (
              <RefreshCw size={14} className="animate-spin" />
            ) : (
              <Plus size={14} />
            )}
            {spawning ? "Spawning…" : "Spawn"}
          </button>
          <span className="text-xs text-slate-500">
            Each node auto-discovers peers via rendezvous (~30s)
          </span>
        </div>

        {orchError && (
          <div className="mb-4 p-3 bg-red-900/30 border border-red-700 rounded-lg text-red-300 text-sm">
            {orchError}
          </div>
        )}

        {/* Running nodes table */}
        {spawnedNodes.length === 0 ? (
          <div className="text-center py-8 text-slate-500">
            <Server size={32} className="mx-auto mb-2 text-slate-600" />
            <p className="text-sm">No dynamically spawned nodes</p>
          </div>
        ) : (
          <div className="space-y-2">
            {spawnedNodes.map((node) => (
              <div
                key={node.node_id}
                className="flex items-center justify-between bg-slate-700/50 rounded-lg px-4 py-3 border border-slate-600"
              >
                <div className="flex items-center gap-4">
                  <div className={`w-2 h-2 rounded-full flex-shrink-0 ${node.status === "running" ? "bg-green-400" : "bg-slate-500"}`} />
                  <code className="text-sm text-aura-accent font-mono">{node.container_name}</code>
                  <span className="text-xs text-slate-500">
                    API :{node.api_port} · P2P :{node.p2p_port}
                  </span>
                  <span className={`text-xs px-2 py-0.5 rounded-full ${node.status === "running" ? "bg-green-900/50 text-green-400" : "bg-slate-700 text-slate-400"}`}>
                    {node.status}
                  </span>
                </div>
                <div className="flex items-center gap-4">
                  <span className="text-xs text-slate-500 flex items-center gap-1">
                    <Clock size={11} />
                    {Math.floor((Date.now() / 1000 - node.spawned_at) / 60)}m ago
                  </span>
                  <button
                    onClick={() => handleStop(node.node_id)}
                    disabled={stoppingId === node.node_id}
                    className="flex items-center gap-1 px-3 py-1 bg-red-900/40 hover:bg-red-900/70 disabled:opacity-50 border border-red-700/50 rounded-lg text-red-400 text-xs transition-colors"
                  >
                    {stoppingId === node.node_id ? (
                      <RefreshCw size={11} className="animate-spin" />
                    ) : (
                      <Square size={11} />
                    )}
                    Stop
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* SSE Connection Error */}
      {error && (
        <div className="mt-4 p-4 bg-red-900/30 border border-red-700 rounded-xl text-red-300">
          <strong>Connection Error:</strong> {error.message}
          <button
            onClick={reconnect}
            className="ml-4 text-sm underline hover:no-underline"
          >
            Retry
          </button>
        </div>
      )}
    </div>
  );
}
