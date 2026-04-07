"use client";

import { useState, useEffect, useCallback, useRef } from "react";

export interface SSEEvent {
  event: string;
  data: unknown;
}

export interface UseSSEOptions {
  url: string;
  enabled?: boolean;
  onEvent?: (event: SSEEvent) => void;
  onError?: (error: Error) => void;
  onOpen?: () => void;
  onClose?: () => void;
}

export interface UseSSEReturn {
  connected: boolean;
  error: Error | null;
  lastEvent: SSEEvent | null;
  reconnect: () => void;
  close: () => void;
}

export function useSSE({
  url,
  enabled = true,
  onEvent,
  onError,
  onOpen,
  onClose,
}: UseSSEOptions): UseSSEReturn {
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [lastEvent, setLastEvent] = useState<SSEEvent | null>(null);
  const eventSourceRef = useRef<EventSource | null>(null);

  const close = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
      setConnected(false);
      onClose?.();
    }
  }, [onClose]);

  const connect = useCallback(() => {
    if (!enabled || !url) return;

    // Close existing connection
    close();

    try {
      const eventSource = new EventSource(url);
      eventSourceRef.current = eventSource;

      eventSource.onopen = () => {
        setConnected(true);
        setError(null);
        onOpen?.();
      };

      eventSource.onerror = (e) => {
        const err = new Error("SSE connection error");
        setError(err);
        setConnected(false);
        onError?.(err);
      };

      // Listen for all event types we care about
      const eventTypes = ["token", "sources", "done", "error", "federation", "peers", "metrics"];

      eventTypes.forEach((eventType) => {
        eventSource.addEventListener(eventType, (e: MessageEvent) => {
          try {
            const data = JSON.parse(e.data);
            const sseEvent: SSEEvent = { event: eventType, data };
            setLastEvent(sseEvent);
            onEvent?.(sseEvent);
          } catch (parseError) {
            console.error("Failed to parse SSE data:", parseError);
          }
        });
      });

      // Also handle generic message events
      eventSource.onmessage = (e) => {
        try {
          const data = JSON.parse(e.data);
          const sseEvent: SSEEvent = { event: "message", data };
          setLastEvent(sseEvent);
          onEvent?.(sseEvent);
        } catch (parseError) {
          // Ignore parse errors for generic messages
        }
      };
    } catch (err) {
      const error = err instanceof Error ? err : new Error("Failed to create EventSource");
      setError(error);
      onError?.(error);
    }
  }, [url, enabled, close, onEvent, onError, onOpen]);

  useEffect(() => {
    connect();
    return () => close();
  }, [connect, close]);

  const reconnect = useCallback(() => {
    close();
    setTimeout(connect, 100);
  }, [close, connect]);

  return { connected, error, lastEvent, reconnect, close };
}

/**
 * Hook for streaming query responses
 */
export interface QueryStreamState {
  isStreaming: boolean;
  tokens: string[];
  fullText: string;
  sources: Array<{
    cid: string;
    page: number;
    score: number;
    text: string;
  }>;
  federationInfo: {
    local_count: number;
    peer_count: number;
    peers_responded: string[];
  } | null;
  queryId: string | null;
  duration_ms: number | null;
  carbon_grams: number | null;
  error: string | null;
}

export function useQueryStream(url: string | null): QueryStreamState & { reset: () => void } {
  const [state, setState] = useState<QueryStreamState>({
    isStreaming: false,
    tokens: [],
    fullText: "",
    sources: [],
    federationInfo: null,
    queryId: null,
    duration_ms: null,
    carbon_grams: null,
    error: null,
  });

  const reset = useCallback(() => {
    setState({
      isStreaming: false,
      tokens: [],
      fullText: "",
      sources: [],
      federationInfo: null,
      queryId: null,
      duration_ms: null,
      carbon_grams: null,
      error: null,
    });
  }, []);

  useEffect(() => {
    if (!url) return;

    reset();
    setState((s) => ({ ...s, isStreaming: true }));

    const eventSource = new EventSource(url);

    eventSource.addEventListener("federation", (e: MessageEvent) => {
      const data = JSON.parse(e.data);
      setState((s) => ({ ...s, federationInfo: data }));
    });

    eventSource.addEventListener("token", (e: MessageEvent) => {
      const data = JSON.parse(e.data);
      setState((s) => ({
        ...s,
        tokens: [...s.tokens, data.token],
        fullText: s.fullText + data.token,
      }));
    });

    eventSource.addEventListener("sources", (e: MessageEvent) => {
      const data = JSON.parse(e.data);
      setState((s) => ({ ...s, sources: data.sources || [] }));
    });

    eventSource.addEventListener("done", (e: MessageEvent) => {
      const data = JSON.parse(e.data);
      setState((s) => ({
        ...s,
        isStreaming: false,
        queryId: data.query_id,
        duration_ms: data.duration_ms,
        carbon_grams: data.carbon_grams,
      }));
      eventSource.close();
    });

    eventSource.addEventListener("error", (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data);
        setState((s) => ({ ...s, isStreaming: false, error: data.error }));
      } catch {
        setState((s) => ({ ...s, isStreaming: false, error: "Connection error" }));
      }
      eventSource.close();
    });

    eventSource.onerror = () => {
      setState((s) => ({ ...s, isStreaming: false, error: "Connection lost" }));
      eventSource.close();
    };

    return () => {
      eventSource.close();
    };
  }, [url, reset]);

  return { ...state, reset };
}
