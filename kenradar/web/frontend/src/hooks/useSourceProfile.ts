/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import { useState, useEffect, useCallback } from 'react';
import type { SourceMetricsTimeSeries } from '../types';

export function useSourceProfile(sourceId: number | undefined, days = 30) {
  const [data, setData] = useState<SourceMetricsTimeSeries | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!sourceId) return;
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`/api/insights/sources/metrics?id=${sourceId}&days=${days}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const profile = await res.json();
      try {
        const topicRes = await fetch(`/api/insights/sources/topics?id=${sourceId}&days=${days}`);
        if (topicRes.ok) {
          const topics = await topicRes.json();
          profile.topics = topics.topics || [];
        }
      } catch {
        profile.topics = [];
      }
      setData(profile);
    } catch (e: any) {
      setError(e.message || String(e));
    } finally {
      setLoading(false);
    }
  }, [sourceId, days]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return { data, loading, error, refresh };
}
