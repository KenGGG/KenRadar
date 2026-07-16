/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 *
 * AsyncState — Unified loading / error / empty / success wrapper.
 * Replaces ad-hoc spinner + error text scattered across components.
 */

import React from 'react';
import { AlertTriangle, Loader2, Inbox } from 'lucide-react';

interface AsyncStateProps {
  loading: boolean;
  error?: string | null;
  empty?: boolean;
  skeleton?: React.ReactNode;
  emptyView?: React.ReactNode;
  errorView?: React.ReactNode;
}

export function AsyncState({
  loading,
  error,
  empty,
  skeleton,
  emptyView,
  errorView,
  children,
}: React.PropsWithChildren<AsyncStateProps>) {
  if (loading) {
    return (
      <div className="flex items-center justify-center py-20 text-zinc-400 dark:text-[var(--text-muted)]">
        {skeleton ?? (
          <>
            <Loader2 className="w-6 h-6 animate-spin text-zinc-300 dark:text-[var(--text-muted)] mr-2" />
            <span className="text-sm">加载中...</span>
          </>
        )}
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-lg border border-red-200 dark:border-[var(--danger-border)] bg-red-50/60 dark:bg-[var(--danger-bg)] p-6 text-center">
        <AlertTriangle className="w-8 h-8 text-red-400 dark:text-[var(--danger)] mx-auto mb-2" />
        <p className="text-sm font-semibold text-red-800 dark:text-[var(--danger)]">加载失败</p>
        <p className="text-xs text-red-600 dark:text-[var(--danger)] mt-1">{error}</p>
        {errorView}
      </div>
    );
  }

  if (empty) {
    return (
      <div className="rounded-lg border border-dashed border-zinc-200 dark:border-[var(--surface-border)] bg-white dark:bg-[var(--surface)] p-10 text-center">
        <Inbox className="w-8 h-8 text-zinc-300 dark:text-[var(--text-muted)] mx-auto mb-2" />
        <p className="text-sm font-medium text-zinc-500 dark:text-[var(--text-secondary)]">暂无数据</p>
        {emptyView}
      </div>
    );
  }

  return <>{children}</>;
}
