/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import { useState, useEffect, useCallback } from 'react';

export interface DashboardSummary {
  today_new: number;
  high_value_pending: number;
  failed: number;
  processing: number;
}

export interface DailyTrendPoint {
  date: string;
  total: number;
  highValue: number;
  pushed: number;
  confirmed: number;
}

export interface PipelineStage {
  downloading: number;
  transcribing: number;
  ai_waiting: number;
  push_waiting: number;
  success: number;
  failed: number;
}

export interface DashboardOverviewData {
  summary: DashboardSummary;
  dailyTrend: DailyTrendPoint[];
  pipeline: PipelineStage;
  failureReasons: { stage: string; count: number }[];
  scoreDistribution: { bucket: string; count: number }[];
  highValueThreshold: number;
}

export interface UseDashboardOverviewReturn {
  data: DashboardOverviewData | null;
  loading: boolean;
  error: string | null;
  refresh: () => void;
}

export function useDashboardOverview(days = 30): UseDashboardOverviewReturn {
  const [data, setData] = useState<DashboardOverviewData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`/api/dashboard/overview?days=${days}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();
      setData(json);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [days]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  return { data, loading, error, refresh: fetchData };
}
