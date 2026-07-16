/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 *
 * Hook for fetching content items from the server-side API with
 * debounced search, filtering, and cursor-based pagination.
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import { VideoContent } from '../types';

interface ContentItemsParams {
  keyword?: string;
  creator_id?: number;
  platform?: string;
  status?: string;
  high_value?: boolean;
  reviewed?: boolean;
  date_from?: string;
  date_to?: string;
  sort?: string;
}

interface ContentItemsResponse {
  items: VideoContent[];
  next_cursor: string | null;
  has_more: boolean;
  high_value_threshold: number;
  applied_filters: Record<string, unknown>;
  total_estimate: number | null;
  message?: string;
}

function buildQuery(params: ContentItemsParams, cursor?: string): URLSearchParams {
  const qs = new URLSearchParams();
  if (params.keyword) qs.set('keyword', params.keyword);
  if (params.creator_id) qs.set('creator_id', String(params.creator_id));
  if (params.platform) qs.set('platform', params.platform);
  if (params.status) qs.set('status', params.status);
  if (params.high_value !== undefined) qs.set('high_value', String(params.high_value));
  if (params.reviewed !== undefined) qs.set('reviewed', String(params.reviewed));
  if (params.date_from) qs.set('date_from', params.date_from);
  if (params.date_to) qs.set('date_to', params.date_to);
  if (params.sort) qs.set('sort', params.sort);
  if (cursor) qs.set('cursor', cursor);
  qs.set('limit', '30');
  return qs;
}

export function useContentItems(initialParams: ContentItemsParams = {}) {
  const [items, setItems] = useState<VideoContent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [highValueThreshold, setHighValueThreshold] = useState<number>(7);
  const [appliedFilters, setAppliedFilters] = useState<Record<string, unknown>>({});

  const abortRef = useRef<AbortController | null>(null);
  const debounceTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const paramsRef = useRef<ContentItemsParams>(initialParams);
  const pageRef = useRef(0); // 0 = fresh load, 1+ = infinite scroll

  const fetchData = useCallback(async (append = false) => {
    // Cancel any in-flight request
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    if (!append) {
      pageRef.current = 0;
      setItems([]);
    }

    try {
      if (loading && !append) setLoading(true);
      setError(null);

      const cursor = append && nextCursor ? nextCursor : undefined;
      const params = { ...paramsRef.current };
      const qs = buildQuery(params, cursor);

      const res = await fetch(`/api/content-items?${qs.toString()}`, {
        credentials: 'same-origin',
        signal: controller.signal,
      });

      const text = await res.text();
      const payload: ContentItemsResponse = text ? JSON.parse(text) : { items: [], next_cursor: null, has_more: false, high_value_threshold: 7, applied_filters: {}, total_estimate: null };

      if (!res.ok || payload.items === undefined) {
        throw new Error(payload.message || `请求失败: ${res.status}`);
      }

      if (!append) {
        setItems(payload.items);
      } else {
        setItems(prev => [...prev, ...payload.items]);
      }

      setHasMore(payload.has_more);
      setNextCursor(payload.next_cursor);
      setHighValueThreshold(payload.high_value_threshold ?? 7);
      setAppliedFilters(payload.applied_filters ?? {});
    } catch (err: unknown) {
      if (err instanceof DOMException && err.name === 'AbortError') return; // cancelled, ignore
      setError(err instanceof Error ? err.message : '加载失败');
    } finally {
      if (!append) setLoading(false);
    }
  }, [loading, nextCursor]);

  // Debounced keyword search
  const setKeyword = useCallback((kw: string | undefined) => {
    paramsRef.current = { ...paramsRef.current, keyword: kw };
    if (debounceTimer.current) clearTimeout(debounceTimer.current);
    debounceTimer.current = setTimeout(() => {
      fetchData(false);
    }, 350);
  }, [fetchData]);

  const setFilter = useCallback((key: keyof ContentItemsParams, value: string | number | boolean | undefined) => {
    paramsRef.current = { ...paramsRef.current, [key]: value };
    // Reset debounce for non-keyword filters
    if (debounceTimer.current) clearTimeout(debounceTimer.current);
    fetchData(false);
  }, [fetchData]);

  const loadMore = useCallback(() => {
    if (!hasMore || loading) return;
    pageRef.current += 1;
    fetchData(true);
  }, [hasMore, loading, fetchData]);

  // Initial load
  useEffect(() => {
    fetchData(false);
    return () => {
      abortRef.current?.abort();
      if (debounceTimer.current) clearTimeout(debounceTimer.current);
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return {
    items,
    loading,
    error,
    hasMore,
    highValueThreshold,
    appliedFilters,
    setKeyword,
    setFilter,
    loadMore,
    refresh: () => fetchData(false),
  };
}
