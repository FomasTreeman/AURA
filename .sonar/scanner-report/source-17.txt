"use client";

import { useState, useCallback, useEffect } from "react";
import {
  Upload, FolderOpen, FileText, CheckCircle2, XCircle,
  Loader2, Trash2, RefreshCw, Database, AlertTriangle,
} from "lucide-react";
import { FileDropzone } from "@/components/FileDropzone";
import {
  uploadFiles, ingestDirectory, fetchStats, fetchDocuments, deleteDocument,
  IngestResult, DocumentEntry,
} from "@/lib/api";

// ── Per-file upload state ─────────────────────────────────────────────────────

type FileStatus = "queued" | "uploading" | "done" | "error";

interface QueuedFile {
  id: string;
  file: File;
  status: FileStatus;
  chunks?: number;
  error?: string;
}

function makeId(f: File) {
  return `${f.name}-${f.size}`;
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function IngestPage() {
  // Upload queue
  const [queue, setQueue] = useState<QueuedFile[]>([]);
  const [isDragging, setIsDragging] = useState(false);
  const [isUploading, setIsUploading] = useState(false);

  // Directory ingest
  const [dirPath, setDirPath] = useState("");
  const [dirStatus, setDirStatus] = useState<"idle" | "loading" | "done" | "error">("idle");
  const [dirResult, setDirResult] = useState<{ files: number; chunks: number } | null>(null);
  const [dirError, setDirError] = useState<string | null>(null);

  // Knowledge base state
  const [docCount, setDocCount] = useState<number | null>(null);
  const [documents, setDocuments] = useState<DocumentEntry[]>([]);
  const [docsLoading, setDocsLoading] = useState(true);
  const [deletingCid, setDeletingCid] = useState<string | null>(null);

  const refreshDocs = useCallback(() => {
    setDocsLoading(true);
    Promise.all([fetchStats(), fetchDocuments()])
      .then(([stats, docs]) => {
        setDocCount(stats.document_count);
        setDocuments(docs.documents);
      })
      .catch(() => {})
      .finally(() => setDocsLoading(false));
  }, []);

  useEffect(() => { refreshDocs(); }, [refreshDocs]);

  // ── File queue ──────────────────────────────────────────────────────────────
  const addFiles = useCallback((incoming: File[]) => {
    setQueue((prev) => {
      const existingIds = new Set(prev.map((q) => q.id));
      const fresh = incoming
        .filter((f) => !existingIds.has(makeId(f)))
        .map((f) => ({ id: makeId(f), file: f, status: "queued" as FileStatus }));
      return [...prev, ...fresh];
    });
  }, []);

  const removeFile = useCallback((id: string) => {
    setQueue((prev) => prev.filter((q) => q.id !== id));
  }, []);

  const clearAll = useCallback(() => setQueue([]), []);
  const clearDone = useCallback(() => {
    setQueue((prev) => prev.filter((q) => q.status !== "done"));
  }, []);

  // ── Upload ──────────────────────────────────────────────────────────────────
  const handleUpload = useCallback(async () => {
    const toUpload = queue.filter((q) => q.status === "queued" || q.status === "error");
    if (!toUpload.length || isUploading) return;

    setIsUploading(true);
    setQueue((prev) =>
      prev.map((q) =>
        q.status === "queued" || q.status === "error" ? { ...q, status: "uploading" } : q
      )
    );

    try {
      const result = await uploadFiles(toUpload.map((q) => q.file));
      const resultMap = new Map<string, IngestResult>(
        result.results.map((r) => [r.file, r])
      );
      setQueue((prev) =>
        prev.map((q) => {
          if (q.status !== "uploading") return q;
          const r = resultMap.get(q.file.name);
          if (!r) return { ...q, status: "done", chunks: 0 };
          if (r.error) return { ...q, status: "error", error: r.error };
          return { ...q, status: "done", chunks: r.chunks_added };
        })
      );
      refreshDocs();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      setQueue((prev) =>
        prev.map((q) => q.status === "uploading" ? { ...q, status: "error", error: msg } : q)
      );
    } finally {
      setIsUploading(false);
    }
  }, [queue, isUploading, refreshDocs]);

  // ── Directory ingest ────────────────────────────────────────────────────────
  const handleDirIngest = useCallback(async () => {
    setDirStatus("loading");
    setDirResult(null);
    setDirError(null);
    try {
      const result = await ingestDirectory(dirPath || undefined);
      setDirResult({ files: result.files_processed, chunks: result.total_chunks });
      setDirStatus("done");
      refreshDocs();
    } catch (e: unknown) {
      setDirError(e instanceof Error ? e.message : String(e));
      setDirStatus("error");
    }
  }, [dirPath, refreshDocs]);

  // ── Delete document ─────────────────────────────────────────────────────────
  const handleDelete = useCallback(async (cid: string) => {
    setDeletingCid(cid);
    try {
      await deleteDocument(cid);
      refreshDocs();
    } catch {
      // leave doc in list with error state handled by refreshDocs
    } finally {
      setDeletingCid(null);
    }
  }, [refreshDocs]);

  // ── Derived ─────────────────────────────────────────────────────────────────
  const queued = queue.filter((q) => q.status === "queued");
  const uploading = queue.filter((q) => q.status === "uploading");
  const done = queue.filter((q) => q.status === "done");
  const failed = queue.filter((q) => q.status === "error");
  const canUpload = (queued.length > 0 || failed.length > 0) && !isUploading;
  const activeDocs = documents.filter((d) => !d.tombstoned);

  return (
    <div className="max-w-3xl mx-auto space-y-6">

      {/* Header */}
      <div className="text-center">
        <h1 className="text-3xl font-bold text-white mb-2">
          <Upload className="inline-block mr-2 text-aura-accent" size={32} />
          Ingest Documents
        </h1>
        <p className="text-slate-400">Add or remove PDFs from your local knowledge node</p>
      </div>

      {/* Stats */}
      <div className="bg-slate-800 rounded-xl border border-slate-700 p-4 flex items-center gap-3">
        <Database size={22} className="text-aura-primary shrink-0" />
        <div>
          <p className="text-xs text-slate-400">Total chunks in store</p>
          <p className="text-2xl font-bold text-white">
            {docCount === null ? "—" : docCount.toLocaleString()}
          </p>
        </div>
        <div className="ml-auto text-right">
          <p className="text-xs text-slate-400">Documents</p>
          <p className="text-2xl font-bold text-white">{activeDocs.length}</p>
        </div>
      </div>

      {/* Upload */}
      <div className="bg-slate-800 rounded-2xl border border-slate-700 p-6 space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold text-white flex items-center gap-2">
            <Upload size={18} className="text-aura-primary" />
            Upload PDFs
          </h2>
          {queue.length > 0 && (
            <div className="flex items-center gap-2">
              {done.length > 0 && (
                <button onClick={clearDone} className="text-xs text-slate-400 hover:text-slate-200 transition-colors px-2 py-1 rounded hover:bg-slate-700">
                  Clear done
                </button>
              )}
              <button onClick={clearAll} disabled={isUploading} className="text-xs text-red-400 hover:text-red-300 transition-colors px-2 py-1 rounded hover:bg-slate-700 disabled:opacity-40">
                Clear all
              </button>
            </div>
          )}
        </div>

        <FileDropzone onFiles={addFiles} disabled={isUploading} isDragging={isDragging} onDragChange={setIsDragging} />

        {queue.length > 0 && (
          <div className="space-y-2">
            {queue.map((q) => (
              <FileCard key={q.id} item={q} onRemove={removeFile} disabled={isUploading} />
            ))}
          </div>
        )}

        <button
          onClick={handleUpload}
          disabled={!canUpload}
          className="w-full py-3 bg-aura-primary hover:bg-aura-primary/80 disabled:bg-slate-700 disabled:cursor-not-allowed rounded-xl text-white font-semibold transition-colors flex items-center justify-center gap-2"
        >
          {isUploading ? (
            <><Loader2 className="animate-spin" size={18} />Ingesting {uploading.length} file{uploading.length !== 1 ? "s" : ""}…</>
          ) : failed.length > 0 && queued.length === 0 ? (
            <><RefreshCw size={18} />Retry {failed.length} failed</>
          ) : (
            <><Upload size={18} />{queued.length > 0 ? `Ingest ${queued.length + failed.length} file${queued.length + failed.length !== 1 ? "s" : ""}` : "Select files above"}</>
          )}
        </button>

        {done.length > 0 && !isUploading && (
          <div className="flex items-center gap-2 text-sm text-green-400 bg-green-400/10 rounded-lg px-4 py-2">
            <CheckCircle2 size={16} />
            {done.length} file{done.length !== 1 ? "s" : ""} ingested · {done.reduce((s, q) => s + (q.chunks ?? 0), 0).toLocaleString()} chunks added
          </div>
        )}
      </div>

      {/* Directory ingest */}
      <div className="bg-slate-800 rounded-2xl border border-slate-700 p-6 space-y-4">
        <h2 className="text-lg font-semibold text-white flex items-center gap-2">
          <FolderOpen size={18} className="text-aura-secondary" />
          Ingest Server Directory
        </h2>
        <p className="text-sm text-slate-400">
          Ingest all PDFs from a server-side path. Leave blank to use the default{" "}
          <code className="text-aura-accent bg-slate-900 px-1.5 py-0.5 rounded text-xs">INGEST_DIR</code>.
        </p>
        <div className="flex gap-3">
          <input
            type="text"
            value={dirPath}
            onChange={(e) => setDirPath(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleDirIngest()}
            placeholder="./data/documents"
            disabled={dirStatus === "loading"}
            className="flex-1 px-4 py-2.5 bg-slate-900 border border-slate-700 rounded-xl text-white placeholder-slate-600 font-mono text-sm focus:outline-none focus:ring-2 focus:ring-aura-secondary disabled:opacity-50 transition-all"
          />
          <button
            onClick={handleDirIngest}
            disabled={dirStatus === "loading"}
            className="px-5 py-2.5 bg-aura-secondary hover:bg-aura-secondary/80 disabled:bg-slate-700 disabled:cursor-not-allowed rounded-xl text-white font-semibold transition-colors flex items-center gap-2 shrink-0"
          >
            {dirStatus === "loading" ? <Loader2 className="animate-spin" size={18} /> : <FolderOpen size={18} />}
            Ingest
          </button>
        </div>
        {dirStatus === "done" && dirResult && (
          <div className="flex items-center gap-2 text-sm text-green-400 bg-green-400/10 rounded-lg px-4 py-2">
            <CheckCircle2 size={16} />
            {dirResult.files} file{dirResult.files !== 1 ? "s" : ""} ingested · {dirResult.chunks.toLocaleString()} chunks added
          </div>
        )}
        {dirStatus === "error" && dirError && (
          <div className="flex items-start gap-2 text-sm text-red-400 bg-red-400/10 rounded-lg px-4 py-3">
            <XCircle size={16} className="shrink-0 mt-0.5" /><span>{dirError}</span>
          </div>
        )}
      </div>

      {/* Knowledge base — existing documents */}
      <div className="bg-slate-800 rounded-2xl border border-slate-700 p-6 space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold text-white flex items-center gap-2">
            <Database size={18} className="text-aura-accent" />
            Knowledge Base
          </h2>
          <button onClick={refreshDocs} disabled={docsLoading} className="text-slate-400 hover:text-white transition-colors p-1.5 rounded hover:bg-slate-700">
            <RefreshCw size={15} className={docsLoading ? "animate-spin" : ""} />
          </button>
        </div>

        {docsLoading ? (
          <div className="flex items-center justify-center py-10 text-slate-500">
            <Loader2 className="animate-spin mr-2" size={18} /> Loading…
          </div>
        ) : activeDocs.length === 0 ? (
          <div className="text-center py-10 text-slate-500">
            <FileText size={36} className="mx-auto mb-2 text-slate-700" />
            <p>No documents ingested yet</p>
            <p className="text-sm mt-1">Upload a PDF above to get started</p>
          </div>
        ) : (
          <div className="space-y-2">
            {activeDocs.map((doc) => (
              <DocumentRow
                key={doc.cid}
                doc={doc}
                deleting={deletingCid === doc.cid}
                onDelete={handleDelete}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ── File card (upload queue) ───────────────────────────────────────────────────

function FileCard({ item, onRemove, disabled }: { item: QueuedFile; onRemove: (id: string) => void; disabled: boolean }) {
  const { id, file, status, chunks, error } = item;

  const icon = {
    queued:    <FileText size={16} className="text-slate-400" />,
    uploading: <Loader2 size={16} className="text-aura-accent animate-spin" />,
    done:      <CheckCircle2 size={16} className="text-green-400" />,
    error:     <XCircle size={16} className="text-red-400" />,
  }[status];

  const border = { queued: "border-slate-700", uploading: "border-aura-accent/40", done: "border-green-500/30", error: "border-red-500/30" }[status];
  const bg     = { queued: "bg-slate-900/50",  uploading: "bg-aura-accent/5",       done: "bg-green-500/5",    error: "bg-red-500/5"    }[status];

  return (
    <div className={`flex items-center gap-3 px-4 py-3 rounded-xl border ${border} ${bg} transition-all`}>
      {icon}
      <div className="flex-1 min-w-0">
        <p className="text-sm text-white font-medium truncate">{file.name}</p>
        <div className="flex items-center gap-3 mt-0.5">
          <span className="text-xs text-slate-500">{(file.size / 1024 / 1024).toFixed(1)} MB</span>
          {status === "uploading" && <span className="text-xs text-aura-accent">Ingesting…</span>}
          {status === "done" && chunks !== undefined && <span className="text-xs text-green-400">+{chunks.toLocaleString()} chunks</span>}
          {status === "error" && error && <span className="text-xs text-red-400 truncate">{error}</span>}
        </div>
      </div>
      {status === "uploading" ? (
        <div className="w-24 h-1.5 bg-slate-700 rounded-full overflow-hidden">
          <div className="h-full bg-aura-accent/60 rounded-full w-1/2 animate-[shimmer_1.5s_ease-in-out_infinite]" />
        </div>
      ) : (
        <button onClick={() => onRemove(id)} disabled={disabled} className="text-slate-600 hover:text-red-400 transition-colors p-1 rounded disabled:opacity-40">
          <Trash2 size={15} />
        </button>
      )}
    </div>
  );
}

// ── Document row (knowledge base) ─────────────────────────────────────────────

function DocumentRow({ doc, deleting, onDelete }: { doc: DocumentEntry; deleting: boolean; onDelete: (cid: string) => void }) {
  const [confirming, setConfirming] = useState(false);

  return (
    <div className="flex items-center gap-3 px-4 py-3 rounded-xl border border-slate-700 bg-slate-900/50 group">
      <FileText size={16} className="text-slate-400 shrink-0" />
      <div className="flex-1 min-w-0">
        <p className="text-sm text-white font-medium truncate">{doc.source}</p>
        <div className="flex items-center gap-3 mt-0.5">
          <span className="text-xs text-slate-500">{doc.chunks.toLocaleString()} chunks</span>
          <span className="text-xs text-slate-600">·</span>
          <span className="text-xs text-slate-500">{doc.page_count} pages</span>
          <span className="text-xs text-slate-700 font-mono hidden sm:inline">{doc.cid.slice(0, 12)}…</span>
        </div>
      </div>

      {confirming ? (
        <div className="flex items-center gap-2 shrink-0">
          <span className="text-xs text-red-400 flex items-center gap-1">
            <AlertTriangle size={12} /> Remove?
          </span>
          <button
            onClick={() => { onDelete(doc.cid); setConfirming(false); }}
            disabled={deleting}
            className="text-xs px-2 py-1 bg-red-500/20 hover:bg-red-500/30 text-red-400 rounded transition-colors disabled:opacity-40"
          >
            {deleting ? <Loader2 size={12} className="animate-spin" /> : "Yes, delete"}
          </button>
          <button onClick={() => setConfirming(false)} className="text-xs px-2 py-1 text-slate-400 hover:text-white rounded hover:bg-slate-700 transition-colors">
            Cancel
          </button>
        </div>
      ) : (
        <button
          onClick={() => setConfirming(true)}
          className="text-slate-700 hover:text-red-400 transition-colors p-1 rounded opacity-0 group-hover:opacity-100"
          title="Delete document"
        >
          <Trash2 size={15} />
        </button>
      )}
    </div>
  );
}
