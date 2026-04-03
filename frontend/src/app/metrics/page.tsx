"use client";

import { useState, useEffect, useCallback } from "react";
import {
  BarChart3,
  Cpu,
  HardDrive,
  Activity,
  Leaf,
  Clock,
  TrendingUp,
  RefreshCw,
  Zap,
  Users,
} from "lucide-react";
import { useSSE, SSEEvent } from "@/hooks/useSSE";
import { fetchGreenOpsStatus, getStreamMetricsUrl, GreenOpsStatus } from "@/lib/api";

interface MetricsUpdate {
  queries_total: number;
  queries_successful: number;
  queries_failed: number;
  peers_connected: number;
  cpu_usage_percent: number;
  memory_usage_bytes: number;
  carbon_estimate_grams: number;
  grid_intensity_gco2_kwh: number;
  uptime_seconds: number;
  timestamp: number;
}

function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${(bytes / Math.pow(k, i)).toFixed(1)} ${sizes[i]}`;
}

function formatUptime(seconds: number): string {
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);

  if (days > 0) return `${days}d ${hours}h`;
  if (hours > 0) return `${hours}h ${minutes}m`;
  return `${minutes}m`;
}

export default function MetricsPage() {
  const [metrics, setMetrics] = useState<MetricsUpdate | null>(null);
  const [greenOps, setGreenOps] = useState<GreenOpsStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [grafanaUrl] = useState(
    process.env.NEXT_PUBLIC_GRAFANA_URL || "http://localhost:3001"
  );

  // Fetch GreenOps status
  useEffect(() => {
    async function fetchStatus() {
      try {
        const status = await fetchGreenOpsStatus();
        setGreenOps(status);
      } catch (err) {
        console.error("Failed to fetch greenops:", err);
      } finally {
        setLoading(false);
      }
    }
    fetchStatus();
    const interval = setInterval(fetchStatus, 30000); // Refresh every 30s
    return () => clearInterval(interval);
  }, []);

  // SSE for real-time metrics
  const handleMetricsEvent = useCallback((event: SSEEvent) => {
    if (event.event === "metrics") {
      setMetrics(event.data as MetricsUpdate);
      setLoading(false);
    }
  }, []);

  const { connected, error, reconnect } = useSSE({
    url: getStreamMetricsUrl(5),
    enabled: true,
    onEvent: handleMetricsEvent,
  });

  const isLowCarbon = greenOps?.is_low_carbon ?? false;
  const gridIntensity = metrics?.grid_intensity_gco2_kwh ?? greenOps?.grid_intensity_gco2_kwh ?? 0;

  return (
    <div className="max-w-6xl mx-auto">
      {/* Header */}
      <div className="text-center mb-8">
        <h1 className="text-3xl font-bold text-white mb-2">
          <BarChart3 className="inline-block mr-2 text-aura-accent" size={32} />
          Observability
        </h1>
        <p className="text-slate-400">
          Real-time metrics, performance, and carbon footprint monitoring
        </p>
      </div>

      {/* Connection Status */}
      <div className="flex items-center justify-end gap-2 mb-4 text-sm">
        <Activity
          size={14}
          className={connected ? "text-green-400" : "text-slate-500"}
        />
        <span className="text-slate-400">
          {connected ? "Live updates" : "Connecting..."}
        </span>
        <button
          onClick={reconnect}
          className="ml-2 text-slate-400 hover:text-white"
        >
          <RefreshCw size={14} />
        </button>
      </div>

      {/* Key Metrics Grid */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
        {/* Queries */}
        <div className="bg-slate-800 rounded-xl border border-slate-700 p-4">
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm text-slate-400">Total Queries</span>
            <TrendingUp size={16} className="text-aura-primary" />
          </div>
          <span className="text-3xl font-bold text-white">
            {metrics?.queries_total ?? 0}
          </span>
          <div className="mt-1 text-xs text-slate-500">
            {metrics?.queries_failed ?? 0} failed
          </div>
        </div>

        {/* Peers */}
        <div className="bg-slate-800 rounded-xl border border-slate-700 p-4">
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm text-slate-400">Peers</span>
            <Users size={16} className="text-aura-secondary" />
          </div>
          <span className="text-3xl font-bold text-white">
            {metrics?.peers_connected ?? 0}
          </span>
          <div className="mt-1 text-xs text-slate-500">connected</div>
        </div>

        {/* CPU */}
        <div className="bg-slate-800 rounded-xl border border-slate-700 p-4">
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm text-slate-400">CPU Usage</span>
            <Cpu size={16} className="text-yellow-400" />
          </div>
          <span className="text-3xl font-bold text-white">
            {(metrics?.cpu_usage_percent ?? 0).toFixed(1)}%
          </span>
          <div className="mt-2 h-2 bg-slate-700 rounded-full overflow-hidden">
            <div
              className="h-full bg-yellow-400 transition-all"
              style={{ width: `${Math.min(metrics?.cpu_usage_percent ?? 0, 100)}%` }}
            />
          </div>
        </div>

        {/* Memory */}
        <div className="bg-slate-800 rounded-xl border border-slate-700 p-4">
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm text-slate-400">Memory</span>
            <HardDrive size={16} className="text-blue-400" />
          </div>
          <span className="text-3xl font-bold text-white">
            {formatBytes(metrics?.memory_usage_bytes ?? 0)}
          </span>
          <div className="mt-1 text-xs text-slate-500">RSS</div>
        </div>
      </div>

      {/* GreenOps Section */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-8">
        {/* Carbon Footprint */}
        <div className="bg-slate-800 rounded-xl border border-slate-700 p-6">
          <h2 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
            <Leaf size={18} className="text-green-400" />
            Carbon Footprint
          </h2>

          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <span className="text-slate-400">Total Emissions</span>
              <span className="text-2xl font-bold text-white">
                {(metrics?.carbon_estimate_grams ?? greenOps?.total_carbon_grams ?? 0).toFixed(4)}g
                <span className="text-sm text-slate-400 ml-1">CO₂</span>
              </span>
            </div>

            <div className="flex items-center justify-between">
              <span className="text-slate-400">Grid Intensity</span>
              <span className={`text-xl font-semibold ${isLowCarbon ? "text-green-400" : "text-yellow-400"}`}>
                {gridIntensity.toFixed(0)}
                <span className="text-sm text-slate-400 ml-1">gCO₂/kWh</span>
              </span>
            </div>

            <div className="pt-2 border-t border-slate-700">
              <div className="flex items-center gap-2">
                <Zap size={16} className={isLowCarbon ? "text-green-400" : "text-yellow-400"} />
                <span className={isLowCarbon ? "text-green-400" : "text-yellow-400"}>
                  {isLowCarbon ? "Low Carbon Window" : "Normal Grid Intensity"}
                </span>
              </div>
              <p className="text-xs text-slate-500 mt-1">
                Threshold: {greenOps?.carbon_threshold_gco2_kwh ?? 200} gCO₂/kWh
              </p>
            </div>
          </div>
        </div>

        {/* Scheduler Status */}
        <div className="bg-slate-800 rounded-xl border border-slate-700 p-6">
          <h2 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
            <Clock size={18} className="text-aura-accent" />
            Carbon-Aware Scheduler
          </h2>

          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <span className="text-slate-400">Status</span>
              <span className={`font-medium ${greenOps?.scheduler_running ? "text-green-400" : "text-slate-500"}`}>
                {greenOps?.scheduler_running ? "Running" : "Stopped"}
              </span>
            </div>

            <div className="flex items-center justify-between">
              <span className="text-slate-400">Queued Tasks</span>
              <span className="text-xl font-semibold text-white">
                {greenOps?.queued_tasks ?? 0}
              </span>
            </div>

            <div className="flex items-center justify-between">
              <span className="text-slate-400">Deferred Queries</span>
              <span className="text-xl font-semibold text-white">
                {greenOps?.queries_deferred ?? 0}
              </span>
            </div>

            {greenOps?.tasks && greenOps.tasks.length > 0 && (
              <div className="pt-2 border-t border-slate-700">
                <p className="text-sm text-slate-400 mb-2">Pending Tasks:</p>
                {greenOps.tasks.slice(0, 3).map((task, i) => (
                  <div key={i} className="text-xs text-slate-500 flex justify-between">
                    <span>{task.name}</span>
                    <span>{task.priority}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Uptime */}
      <div className="bg-slate-800 rounded-xl border border-slate-700 p-6 mb-8">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Activity size={18} className="text-aura-primary" />
            <span className="text-slate-400">Uptime</span>
          </div>
          <span className="text-2xl font-bold text-white">
            {formatUptime(metrics?.uptime_seconds ?? 0)}
          </span>
        </div>
      </div>

      {/* Grafana Embed Section */}
      <div className="bg-slate-800 rounded-xl border border-slate-700 p-6">
        <h2 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
          <BarChart3 size={18} className="text-aura-secondary" />
          Grafana Dashboard
        </h2>

        <div className="bg-slate-900 rounded-lg border border-slate-700 overflow-hidden">
          {/* Placeholder for Grafana iframe */}
          <div className="aspect-video flex items-center justify-center text-slate-500">
            <div className="text-center">
              <BarChart3 size={48} className="mx-auto mb-4 text-slate-600" />
              <p>Grafana dashboard available at:</p>
              <a
                href={grafanaUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="text-aura-accent hover:underline"
              >
                {grafanaUrl}
              </a>
              <p className="text-sm mt-2">
                Import the dashboard from <code className="bg-slate-800 px-2 py-1 rounded">docs/grafana/dashboard.json</code>
              </p>
            </div>
          </div>
          {/* Uncomment below to embed Grafana when available */}
          {/* <iframe
            src={`${grafanaUrl}/d/aura-overview?orgId=1&refresh=5s&theme=dark&kiosk`}
            className="w-full aspect-video border-0"
            title="Grafana Dashboard"
          /> */}
        </div>
      </div>

      {/* Error Display */}
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
