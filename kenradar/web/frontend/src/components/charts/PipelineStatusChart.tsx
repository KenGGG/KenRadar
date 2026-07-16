/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React from 'react';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from 'recharts';

interface PipelineStage {
  downloading: number;
  transcribing: number;
  ai_waiting: number;
  push_waiting: number;
  success: number;
  failed: number;
}

interface PipelineStatusChartProps {
  data: PipelineStage;
  title?: string;
}

const STAGE_LABELS: Record<keyof PipelineStage, string> = {
  downloading: '下载中',
  transcribing: '转写中',
  ai_waiting: 'AI 等待',
  push_waiting: '推送等待',
  success: '已完成',
  failed: '失败',
};

const STAGE_COLORS: Record<keyof PipelineStage, string> = {
  downloading: '#3b82f6',
  transcribing: '#a855f7',
  ai_waiting: '#f59e0b',
  push_waiting: '#06b6d4',
  success: '#10b981',
  failed: '#ef4444',
};

export default function PipelineStatusChart({
  data,
  title = '流水线状态',
}: PipelineStatusChartProps) {
  const chartData = Object.entries(data).map(([key, value]) => ({
    stage: STAGE_LABELS[key as keyof PipelineStage],
    key,
    count: value,
  }));

  const total = chartData.reduce((sum, d) => sum + d.count, 0);

  if (total === 0) {
    return (
      <div className="p-8 text-center text-zinc-400 dark:text-[var(--text-muted)] text-sm font-sans">
        暂无流水线数据
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <h3 className="text-sm font-semibold text-zinc-700 dark:text-[var(--text-primary)] font-sans">
        {title}
      </h3>
      <ResponsiveContainer width="100%" height={260}>
        <BarChart data={chartData} layout="vertical" margin={{ top: 4, right: 24, bottom: 4, left: -8 }}>
          <defs>
            <linearGradient id="barSuccess" x1="0" y1="0" x2="1" y2="0">
              <stop offset="0%" stopColor={STAGE_COLORS.success} stopOpacity={0.6} />
              <stop offset="100%" stopColor={STAGE_COLORS.success} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="currentColor" className="text-zinc-200 dark:text-zinc-700" horizontal={false} />
          <XAxis
            type="number"
            tick={{ fontSize: 11, fontFamily: 'sans-serif' }}
            stroke="currentColor"
          />
          <YAxis
            type="category"
            dataKey="stage"
            tick={{ fontSize: 12, fontFamily: 'sans-serif' }}
            width={80}
            stroke="currentColor"
          />
          <Tooltip
            contentStyle={{
              backgroundColor: 'var(--surface, #fff)',
              border: '1px solid var(--surface-border, #e5e7eb)',
              borderRadius: '0.5rem',
              fontSize: '12px',
              fontFamily: 'sans-serif',
              color: 'var(--text-primary, #18181b)',
            }}
            formatter={(value: number) => [value, '数量']}
          />
          <Bar dataKey="count" radius={[0, 4, 4, 0]} barSize={20}>
            {chartData.map((entry, index) => (
              <Cell
                key={entry.key}
                fill={STAGE_COLORS[entry.key as keyof PipelineStage]}
                fillOpacity={entry.count === 0 ? 0.15 : 1}
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
      <div className="flex flex-wrap gap-3 pt-1">
        {chartData.map(({ key, count }) => (
          <div key={key} className="flex items-center gap-1.5 text-xs font-sans">
            <span
              className="w-2.5 h-2.5 rounded-sm inline-block"
              style={{ backgroundColor: STAGE_COLORS[key as keyof PipelineStage] }}
            />
            <span className="text-zinc-500 dark:text-[var(--text-muted)]">
              {STAGE_LABELS[key as keyof PipelineStage]}
            </span>
            <span className="font-semibold text-zinc-700 dark:text-[var(--text-primary)]">
              {count}
            </span>
          </div>
        ))}
        <span className="ml-auto text-xs font-sans font-semibold text-zinc-500 dark:text-[var(--text-muted)]">
          总计 {total}
        </span>
      </div>
    </div>
  );
}
