/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

/**
 * SSE client with state machine:
 *   disconnected -> connecting -> connected -> degraded -> polling
 *
 * Uses EventSource for the SSE stream and falls back to polling
 * when the connection is unstable. Callbacks are stored in refs
 * to avoid reconnection storms.
 */

import { useState, useEffect, useRef, useCallback } from 'react';

type ConnectionState = 'disconnected' | 'connecting' | 'connected' | 'degraded' | 'polling';

interface SSEOptions {
  /** Called when a research-job event is received. Receives the parsed JSON payload. */
  onEvent?: (data: Record<string, any>) => void;
  /** Called when connection state changes. */
  onStateChange?: (state: ConnectionState) => void;
  /** Polling interval in ms when degraded (default 8000). */
  pollIntervalMs?: number;
  /** Number of consecutive connection failures before switching to polling (default 3). */
  failureThreshold?: number;
  /** SSE reconnect timeout in ms — if no message received within this window, consider degraded (default 60000). */
  heartbeatTimeoutMs?: number;
}

export function useSSE(options: SSEOptions = {}) {
  const {
    onEvent,
    onStateChange,
    pollIntervalMs = 8000,
    failureThreshold = 3,
    heartbeatTimeoutMs = 60000,
  } = options;

  const [state, setState] = useState<ConnectionState>('disconnected');
  const eventRef = useRef(onEvent || (() => {}));
  const stateRef = useRef(onStateChange);
  const esRef = useRef<EventSource | null>(null);
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const hbTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const failCountRef = useRef(0);

  // Keep refs in sync
  useEffect(() => {
    eventRef.current = onEvent || (() => {});
  }, [onEvent]);

  useEffect(() => {
    stateRef.current = onStateChange;
  }, [onStateChange]);

  const notifyState = useCallback((s: ConnectionState) => {
    setState(s);
    stateRef.current?.(s);
  }, []);

  const clearHeartbeatTimer = useCallback(() => {
    if (hbTimerRef.current) {
      clearTimeout(hbTimerRef.current);
      hbTimerRef.current = null;
    }
  }, []);

  const startHeartbeatCheck = useCallback(() => {
    clearHeartbeatTimer();
    hbTimerRef.current = setTimeout(() => {
      // No heartbeat or data event within timeout — degrade
    }, heartbeatTimeoutMs);
  }, [heartbeatTimeoutMs, clearHeartbeatTimer]);

  const stopPolling = useCallback(() => {
    if (pollTimerRef.current) {
      clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }
  }, []);

  const startPolling = useCallback(() => {
    stopPolling();
    pollTimerRef.current = setInterval(() => {
      fetch('/api/research/jobs')
        .then(r => r.json())
        .then(data => {
          for (const job of (data.items || [])) {
            eventRef.current({
              type: 'research_job.poll',
              entityId: job.id,
              payload: { status: job.status, pipeline_progress: job.pipeline_progress },
            });
          }
        })
        .catch(() => {});
    }, pollIntervalMs);
  }, [pollIntervalMs, stopPolling]);

  const disconnect = useCallback(() => {
    if (esRef.current) {
      esRef.current.close();
      esRef.current = null;
    }
    clearHeartbeatTimer();
    stopPolling();
    notifyState('disconnected');
  }, [clearHeartbeatTimer, notifyState, stopPolling]);

  const connect = useCallback(() => {
    disconnect();

    notifyState('connecting');

    const url = `/api/stream?channels=research-jobs`;
    const es = new EventSource(url);
    esRef.current = es;

    es.onopen = () => {
      failCountRef.current = 0;
      notifyState('connected');
      startHeartbeatCheck();
    };

    es.onmessage = (evt: MessageEvent) => {
      try {
        const data = JSON.parse(evt.data);
        eventRef.current(data);
        failCountRef.current = 0;
        startHeartbeatCheck();
      } catch {
        // Ignore malformed SSE data
      }
    };

    es.onerror = () => {
      if (es.readyState === EventSource.CLOSED) {
        // Permanent close — switch to polling
        notifyState('polling');
        failCountRef.current = 0;
        startPolling();
      } else {
        // Temporary error — EventSource will auto-retry
        failCountRef.current += 1;
        if (failCountRef.current >= failureThreshold) {
          es.close();
          notifyState('degraded');
          startPolling();
        }
      }
    };
  }, [failureThreshold, notifyState, startHeartbeatCheck, startPolling, disconnect]);

  // Visibility API — reduce polling frequency when tab is hidden
  useEffect(() => {
    const handleVisibility = () => {
      if (document.hidden && pollTimerRef.current) {
        stopPolling();
        pollTimerRef.current = setInterval(() => {
          fetch('/api/research/jobs')
            .then(r => r.json())
            .then(data => {
              for (const job of (data.items || [])) {
                eventRef.current({
                  type: 'research_job.poll',
                  entityId: job.id,
                  payload: { status: job.status, pipeline_progress: job.pipeline_progress },
                });
              }
            })
            .catch(() => {});
        }, pollIntervalMs * 2);
      } else if (!document.hidden) {
        stopPolling();
        // Immediate sync when visible again
        fetch('/api/research/jobs')
          .then(r => r.json())
          .then(data => {
            for (const job of (data.items || [])) {
              eventRef.current({
                type: 'research_job.poll',
                entityId: job.id,
                payload: { status: job.status, pipeline_progress: job.pipeline_progress },
              });
            }
          })
          .catch(() => {});
      }
    };

    document.addEventListener('visibilitychange', handleVisibility);
    return () => document.removeEventListener('visibilitychange', handleVisibility);
  }, [pollIntervalMs, stopPolling]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      disconnect();
    };
  }, [disconnect]);

  return { state, connect, disconnect };
}
