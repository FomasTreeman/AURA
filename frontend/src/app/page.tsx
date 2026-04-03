"use client";

import { useState, useCallback, useRef, useEffect } from "react";
import { Send, Loader2, FileText, Clock, Leaf, Users, Sparkles, History, ChevronDown, ChevronRight } from "lucide-react";
import { useQueryStream } from "@/hooks/useSSE";
import {
  getStreamQueryUrl,
  fetchChatHistory,
  fetchChatSession,
  type ChatHistoryEntry,
  type ChatSessionDetail,
} from "@/lib/api";

export default function QueryPage() {
  const [question, setQuestion] = useState("");
  const [streamUrl, setStreamUrl] = useState<string | null>(null);
  const answerRef = useRef<HTMLDivElement>(null);

  const queryState = useQueryStream(streamUrl);

  // History state
  const [history, setHistory] = useState<ChatHistoryEntry[]>([]);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [expandedDetail, setExpandedDetail] = useState<ChatSessionDetail | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);

  const loadHistory = useCallback(() => {
    fetchChatHistory(30).then((r) => setHistory(r.sessions)).catch(() => {});
  }, []);

  // Load history on mount
  useEffect(() => { loadHistory(); }, [loadHistory]);

  // Refresh history when a query completes
  useEffect(() => {
    if (!queryState.isStreaming && queryState.queryId) {
      loadHistory();
    }
  }, [queryState.isStreaming, queryState.queryId, loadHistory]);

  const handleHistoryClick = useCallback(async (queryId: string) => {
    if (expandedId === queryId) {
      setExpandedId(null);
      setExpandedDetail(null);
      return;
    }
    setExpandedId(queryId);
    setExpandedDetail(null);
    try {
      const detail = await fetchChatSession(queryId);
      setExpandedDetail(detail);
    } catch {
      setExpandedDetail(null);
    }
  }, [expandedId]);

  const handleSubmit = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault();
      if (!question.trim() || queryState.isStreaming) return;
      setStreamUrl(getStreamQueryUrl(question));
    },
    [question, queryState.isStreaming]
  );

  const handleNewQuery = useCallback(() => {
    setStreamUrl(null);
    queryState.reset();
    setQuestion("");
  }, [queryState]);

  // Auto-scroll to bottom while streaming
  useEffect(() => {
    if (answerRef.current && queryState.isStreaming) {
      answerRef.current.scrollTop = answerRef.current.scrollHeight;
    }
  }, [queryState.fullText, queryState.isStreaming]);

  return (
    <div className="max-w-5xl mx-auto">
      {/* Header */}
      <div className="text-center mb-8">
        <h1 className="text-3xl font-bold text-white mb-2">
          <Sparkles className="inline-block mr-2 text-aura-accent" size={32} />
          Ask AURA
        </h1>
        <p className="text-slate-400">
          Query your federated knowledge mesh with natural language
        </p>
      </div>

      {/* Query Form */}
      <form onSubmit={handleSubmit} className="mb-8">
        <div className="relative">
          <input
            type="text"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="Ask a question about your documents..."
            className="w-full px-6 py-4 bg-slate-800 border border-slate-700 rounded-xl text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-aura-primary focus:border-transparent transition-all"
            disabled={queryState.isStreaming}
          />
          <button
            type="submit"
            disabled={!question.trim() || queryState.isStreaming}
            className="absolute right-2 top-1/2 -translate-y-1/2 px-4 py-2 bg-aura-primary hover:bg-aura-primary/80 disabled:bg-slate-700 disabled:cursor-not-allowed rounded-lg text-white font-medium transition-colors flex items-center gap-2"
          >
            {queryState.isStreaming ? (
              <Loader2 className="animate-spin" size={20} />
            ) : (
              <Send size={20} />
            )}
            {queryState.isStreaming ? "Thinking..." : "Ask"}
          </button>
        </div>
      </form>

      {/* Federation Info */}
      {queryState.federationInfo && (
        <div className="mb-4 flex items-center gap-4 text-sm text-slate-400">
          <span className="flex items-center gap-1">
            <FileText size={14} />
            {queryState.federationInfo.local_count} local chunks
          </span>
          {queryState.federationInfo.peer_count > 0 && (
            <span className="flex items-center gap-1 text-aura-accent">
              <Users size={14} />
              {queryState.federationInfo.peer_count} from peers
            </span>
          )}
        </div>
      )}

      {/* Answer Section */}
      {(queryState.fullText || queryState.isStreaming) && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Main Answer */}
          <div className="lg:col-span-2">
            <div className="bg-slate-800 rounded-xl border border-slate-700 p-6">
              <h2 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
                <Sparkles size={18} className="text-aura-accent" />
                Answer
              </h2>
              <div
                ref={answerRef}
                className="prose prose-invert max-w-none max-h-[500px] overflow-y-auto"
              >
                <p className={`text-slate-200 whitespace-pre-wrap ${queryState.isStreaming ? "cursor-blink" : ""}`}>
                  {queryState.fullText || "..."}
                </p>
              </div>

              {/* Query Stats */}
              {!queryState.isStreaming && queryState.duration_ms && (
                <div className="mt-4 pt-4 border-t border-slate-700 flex items-center gap-6 text-sm text-slate-400">
                  <span className="flex items-center gap-1">
                    <Clock size={14} />
                    {(queryState.duration_ms / 1000).toFixed(2)}s
                  </span>
                  {queryState.carbon_grams !== null && (
                    <span className="flex items-center gap-1 text-green-400">
                      <Leaf size={14} />
                      {queryState.carbon_grams.toFixed(4)}g CO₂
                    </span>
                  )}
                  <button
                    onClick={handleNewQuery}
                    className="ml-auto text-aura-accent hover:text-aura-accent/80 transition-colors"
                  >
                    New Query
                  </button>
                </div>
              )}
            </div>
          </div>

          {/* Sources Panel */}
          <div className="lg:col-span-1">
            <div className="bg-slate-800 rounded-xl border border-slate-700 p-6">
              <h2 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
                <FileText size={18} className="text-aura-secondary" />
                Sources
                {queryState.sources.length > 0 && (
                  <span className="text-sm text-slate-400 font-normal">
                    ({queryState.sources.length})
                  </span>
                )}
              </h2>

              {queryState.sources.length === 0 ? (
                <p className="text-slate-500 text-sm">
                  {queryState.isStreaming
                    ? "Loading sources..."
                    : "No sources cited"}
                </p>
              ) : (
                <div className="space-y-3 max-h-[400px] overflow-y-auto">
                  {queryState.sources.map((source, i) => (
                    <div
                      key={`${source.cid}-${i}`}
                      className="source-card bg-slate-700/50 rounded-lg p-3 border border-slate-600"
                    >
                      <div className="flex items-start justify-between mb-2">
                        <span className="text-xs text-aura-accent font-medium">
                          [{i + 1}]
                        </span>
                        <span className="text-xs text-slate-500">
                          Score: {(source.score * 100).toFixed(0)}%
                        </span>
                      </div>
                      <p className="text-sm text-slate-300 line-clamp-3">
                        {source.text}
                      </p>
                      <div className="mt-2 text-xs text-slate-500">
                        Page {source.page} • {source.cid.slice(0, 12)}...
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Error Display */}
      {queryState.error && (
        <div className="mt-4 p-4 bg-red-900/30 border border-red-700 rounded-xl text-red-300">
          <strong>Error:</strong> {queryState.error}
        </div>
      )}

      {/* Empty State */}
      {!queryState.fullText && !queryState.isStreaming && !queryState.error && (
        <div className="text-center py-16 text-slate-500">
          <Sparkles size={48} className="mx-auto mb-4 text-slate-600" />
          <p>Enter a question above to query your knowledge mesh</p>
          <p className="text-sm mt-2">
            AURA will search local documents and federated peers
          </p>
        </div>
      )}

      {/* Chat History */}
      {history.length > 0 && (
        <div className="mt-10">
          <button
            onClick={() => setHistoryOpen((o) => !o)}
            className="flex items-center gap-2 text-slate-400 hover:text-white transition-colors mb-3 text-sm font-medium"
          >
            <History size={16} />
            Recent Queries ({history.length})
            {historyOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          </button>

          {historyOpen && (
            <div className="space-y-2">
              {history.map((entry) => (
                <div key={entry.query_id} className="bg-slate-800 border border-slate-700 rounded-xl overflow-hidden">
                  <button
                    onClick={() => handleHistoryClick(entry.query_id)}
                    className="w-full flex items-start justify-between gap-4 px-5 py-4 text-left hover:bg-slate-700/50 transition-colors"
                  >
                    <div className="flex-1 min-w-0">
                      <p className="text-white font-medium truncate">{entry.question}</p>
                      <p className="text-slate-400 text-sm mt-1 line-clamp-2">{entry.answer_preview}</p>
                    </div>
                    <div className="flex-shrink-0 text-right text-xs text-slate-500 space-y-1">
                      <div className="flex items-center gap-1 justify-end">
                        <Clock size={11} />
                        {(entry.duration_ms / 1000).toFixed(1)}s
                      </div>
                      <div className="flex items-center gap-1 justify-end">
                        <FileText size={11} />
                        {entry.sources_count} sources
                      </div>
                      {expandedId === entry.query_id ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                    </div>
                  </button>

                  {expandedId === entry.query_id && (
                    <div className="border-t border-slate-700 px-5 py-4">
                      {expandedDetail === null ? (
                        <div className="flex items-center gap-2 text-slate-400 text-sm">
                          <Loader2 size={14} className="animate-spin" />
                          Loading…
                        </div>
                      ) : (
                        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
                          <div className="lg:col-span-2">
                            <p className="text-slate-200 whitespace-pre-wrap text-sm leading-relaxed max-h-64 overflow-y-auto">
                              {expandedDetail.answer}
                            </p>
                          </div>
                          {expandedDetail.sources.length > 0 && (
                            <div className="space-y-2 max-h-64 overflow-y-auto">
                              {expandedDetail.sources.map((src, i) => (
                                <div key={`${src.cid}-${i}`} className="bg-slate-700/50 rounded-lg p-3 border border-slate-600">
                                  <div className="flex justify-between mb-1">
                                    <span className="text-xs text-aura-accent font-medium">[{i + 1}]</span>
                                    <span className="text-xs text-slate-500">
                                      {(src.score * 100).toFixed(0)}%
                                    </span>
                                  </div>
                                  <p className="text-xs text-slate-300 line-clamp-3">{src.text}</p>
                                  <p className="text-xs text-slate-500 mt-1">
                                    Page {src.page} · {src.cid.slice(0, 12)}…
                                  </p>
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
