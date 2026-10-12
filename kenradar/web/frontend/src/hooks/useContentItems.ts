/** Server content pages. TanStack Query owns requests and cancellation. */
import { useCallback, useEffect, useRef, useState } from 'react';
import { useInfiniteQuery } from '@tanstack/react-query';
import { VideoContent } from '../types';

interface ContentItemsParams {
  keyword?: string; creator_id?: number; platform?: string; status?: string;
  high_value?: boolean; reviewed?: boolean; date_from?: string; date_to?: string; sort?: string;
}
interface ContentItemsResponse {
  items: VideoContent[]; next_cursor: string | null; has_more: boolean;
  high_value_threshold: number; applied_filters: Record<string, unknown>;
  total_estimate: number | null; message?: string;
  source_counts?: {name: string; total_items: number; note_files: number; successful_notes: number; failed_notes: number}[];
}

export function useContentItems(initialParams: ContentItemsParams = {}) {
  const [params, setParams] = useState(initialParams);
  const debounce = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => () => clearTimeout(debounce.current), []);
  const query = useInfiniteQuery({
    queryKey: ['content-items', params],
    initialPageParam: null as string | null,
    queryFn: async ({ pageParam, signal }): Promise<ContentItemsResponse> => {
      const search = new URLSearchParams({ limit: '30' });
      Object.entries(params).forEach(([key, value]) => { if (value !== undefined && value !== '') search.set(key, String(value)); });
      if (pageParam) search.set('cursor', pageParam);
      const response = await fetch(`/api/content-items?${search}`, { credentials: 'same-origin', signal });
      const data: ContentItemsResponse = await response.json();
      if (!response.ok || !Array.isArray(data.items)) throw new Error(data.message || `读取内容失败 (${response.status})`);
      return data;
    },
    getNextPageParam: page => page.has_more ? page.next_cursor : undefined,
    refetchOnWindowFocus: false,
    staleTime: 15_000,
  });
  const setKeyword = useCallback((keyword: string | undefined) => {
    clearTimeout(debounce.current);
    debounce.current = setTimeout(() => setParams(previous => ({ ...previous, keyword })), 350);
  }, []);
  const setFilter = useCallback((key: keyof ContentItemsParams, value: string | number | boolean | undefined) => {
    clearTimeout(debounce.current);
    setParams(previous => ({ ...previous, [key]: value }));
  }, []);
  return {
    items: query.data?.pages.flatMap(page => page.items) || [],
    loading: query.isFetching, error: query.error?.message || null, hasMore: query.hasNextPage,
    highValueThreshold: query.data?.pages[0]?.high_value_threshold ?? 7,
    totalItems: query.data?.pages[0]?.total_estimate ?? null,
    sourceCounts: query.data?.pages[0]?.source_counts ?? [],
    appliedFilters: query.data?.pages[0]?.applied_filters || {},
    setKeyword, setFilter,
    loadMore: () => { if (query.hasNextPage && !query.isFetching) void query.fetchNextPage(); },
    refresh: () => { void query.refetch(); },
  };
}
