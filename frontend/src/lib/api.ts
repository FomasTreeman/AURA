/**
 * API client for AURA backend
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export interface HealthResponse {
  status: string;
  ollama: { running: boolean; error: string | null };
  vector_store: { count: number };
}

export interface StatsResponse {
  collection: string;
  document_count: number;
}

export interface NetworkStatus {
  running: boolean;
  peer_id: string | null;
  multiaddr: string | null;
  peers: number;
  mdns_enabled: boolean;
}

export interface Peer {
  peer_id: string;
  multiaddrs: string[];
}

export interface PeersResponse {
  count: number;
  peers: Peer[];
}

export interface GreenOpsStatus {
  scheduler_running: boolean;
  grid_intensity_gco2_kwh: number;
  is_low_carbon: boolean;
  carbon_threshold_gco2_kwh: number;
  total_carbon_grams: number;
  queries_deferred: number;
  queued_tasks: number;
  tasks: Array<{
    name: string;
    priority: string;
    age_hours: number;
    max_defer_hours: number;
  }>;
}

export interface SecurityStatus {
  did_active: boolean;
  peer_id: string | null;
  did: string | null;
  revocation_manager_active: boolean;
  tombstoned_cids: number;
  cid_enforcement: string;
  auth_proof_type: string;
}

export async function fetchHealth(): Promise<HealthResponse> {
  const res = await fetch(`${API_BASE}/health`);
  if (!res.ok) throw new Error("Failed to fetch health");
  return res.json();
}

export async function fetchStats(): Promise<StatsResponse> {
  const res = await fetch(`${API_BASE}/stats`);
  if (!res.ok) throw new Error("Failed to fetch stats");
  return res.json();
}

export async function fetchNetworkStatus(): Promise<NetworkStatus> {
  const res = await fetch(`${API_BASE}/network/status`);
  if (!res.ok) throw new Error("Failed to fetch network status");
  return res.json();
}

export async function fetchPeers(): Promise<PeersResponse> {
  const res = await fetch(`${API_BASE}/network/peers`);
  if (!res.ok) throw new Error("Failed to fetch peers");
  return res.json();
}

export async function fetchGreenOpsStatus(): Promise<GreenOpsStatus> {
  const res = await fetch(`${API_BASE}/greenops/status`);
  if (!res.ok) throw new Error("Failed to fetch greenops status");
  return res.json();
}

export async function fetchSecurityStatus(): Promise<SecurityStatus> {
  const res = await fetch(`${API_BASE}/security/status`);
  if (!res.ok) throw new Error("Failed to fetch security status");
  return res.json();
}

export async function fetchMetricsRaw(): Promise<string> {
  const res = await fetch(`${API_BASE}/metrics`);
  if (!res.ok) throw new Error("Failed to fetch metrics");
  return res.text();
}

export interface IngestResult {
  file: string;
  chunks_added: number;
  error?: string;
}

export interface IngestResponse {
  files_processed: number;
  total_chunks: number;
  results: IngestResult[];
}

export async function uploadFiles(files: File[]): Promise<IngestResponse> {
  const form = new FormData();
  files.forEach((f) => form.append("files", f));
  const res = await fetch(`${API_BASE}/ingest/upload`, { method: "POST", body: form });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export interface DocumentEntry {
  cid: string;
  source: string;
  ipfs_cid: string;
  chunks: number;
  page_count: number;
  tombstoned: boolean;
}

export interface DocumentsResponse {
  count: number;
  documents: DocumentEntry[];
}

export async function fetchDocuments(): Promise<DocumentsResponse> {
  const res = await fetch(`${API_BASE}/documents`);
  if (!res.ok) throw new Error("Failed to fetch documents");
  return res.json();
}

export async function deleteDocument(cid: string): Promise<void> {
  const res = await fetch(`${API_BASE}/document/${encodeURIComponent(cid)}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error(await res.text());
}

export async function ingestDirectory(directory?: string): Promise<IngestResponse> {
  const res = await fetch(`${API_BASE}/ingest`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ directory: directory ?? null }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export interface ChatHistoryEntry {
  query_id: string;
  question: string;
  answer_preview: string;
  sources_count: number;
  started_at: number;
  duration_ms: number;
  error: string | null;
}

export interface ChatHistoryResponse {
  count: number;
  sessions: ChatHistoryEntry[];
}

export interface ChatSessionDetail {
  query_id: string;
  question: string;
  answer: string;
  sources: Array<{ source: string; page: number; cid: string; text: string; score: number }>;
  federation_info: Record<string, unknown> | null;
  started_at: number;
  duration_ms: number;
  error: string | null;
}

export interface SpawnedNode {
  node_id: string;
  container_name: string;
  api_port: number;
  p2p_port: number;
  status: string;
  spawned_at: number;
}

export interface SpawnResponse {
  spawned: number;
  nodes: SpawnedNode[];
}

export interface NodesResponse {
  count: number;
  nodes: SpawnedNode[];
}

export async function spawnNodes(count: number): Promise<SpawnResponse> {
  const res = await fetch(`${API_BASE}/nodes/spawn`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ count }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function fetchSpawnedNodes(): Promise<NodesResponse> {
  const res = await fetch(`${API_BASE}/nodes`);
  if (!res.ok) throw new Error("Failed to fetch spawned nodes");
  return res.json();
}

export async function stopNode(nodeId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/nodes/${encodeURIComponent(nodeId)}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error(await res.text());
}

export async function fetchChatHistory(limit = 50): Promise<ChatHistoryResponse> {
  const res = await fetch(`${API_BASE}/chat/history?limit=${limit}`);
  if (!res.ok) throw new Error("Failed to fetch chat history");
  return res.json();
}

export async function fetchChatSession(queryId: string): Promise<ChatSessionDetail> {
  const res = await fetch(`${API_BASE}/chat/history/${encodeURIComponent(queryId)}`);
  if (!res.ok) throw new Error("Failed to fetch chat session");
  return res.json();
}

export function getStreamQueryUrl(question: string): string {
  return `${API_BASE}/stream/query?question=${encodeURIComponent(question)}`;
}

export function getStreamPeersUrl(interval: number = 5): string {
  return `${API_BASE}/stream/peers?interval=${interval}`;
}

export function getStreamMetricsUrl(interval: number = 10): string {
  return `${API_BASE}/stream/metrics?interval=${interval}`;
}
