/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 *
 * Skeleton — Reusable loading placeholders for content areas.
 */

import React from 'react';

interface SkeletonProps {
  className?: string;
}

function Bar({ className = '' }: SkeletonProps) {
  return (
    <div className={`animate-pulse rounded bg-zinc-200 dark:bg-[var(--surface-border)] ${className}`} />
  );
}

export function CardSkeleton({ count = 3 }: { count?: number }) {
  return (
    <div className="space-y-4">
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="rounded-xl border border-zinc-200 dark:border-[var(--surface-border)] bg-white dark:bg-[var(--surface)] p-5 space-y-3">
          <Bar className="h-4 w-2/3" />
          <Bar className="h-3 w-full" />
          <Bar className="h-3 w-4/5" />
          <div className="flex gap-2">
            <Bar className="h-5 w-16 rounded-full" />
            <Bar className="h-5 w-20 rounded-full" />
          </div>
        </div>
      ))}
    </div>
  );
}

export function ListSkeleton({ count = 5 }: { count?: number }) {
  return (
    <div className="divide-y divide-zinc-100 dark:divide-[var(--surface-border)] rounded-lg border border-zinc-150 dark:border-[var(--surface-border)] bg-white dark:bg-[var(--surface)]">
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="p-4 space-y-2 animate-pulse">
          <Bar className="h-4 w-3/4" />
          <Bar className="h-3 w-1/2" />
          <Bar className="h-3 w-1/4" />
        </div>
      ))}
    </div>
  );
}

export function GridSkeleton({ cols = 4, count = 4 }: { cols?: number; count?: number }) {
  return (
    <div className={`grid grid-cols-${cols} gap-3`}>
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="rounded-lg border border-zinc-150 dark:border-[var(--surface-border)] bg-white dark:bg-[var(--surface)] p-4 space-y-2 animate-pulse">
          <Bar className="h-3 w-2/3" />
          <Bar className="h-6 w-1/2" />
        </div>
      ))}
    </div>
  );
}
