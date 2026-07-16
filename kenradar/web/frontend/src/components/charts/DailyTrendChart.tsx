/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React from 'react';
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';

interface DailyTrendPoint {
  date: string;
  total: number;
  highValue: number;
  pushed: number;
  confirmed: number;
}

interface DailyTrendChartProps {
  data: DailyTrendPoint[];
  title?: string;
}

const COLORS = {
  total: '#3b82f6',
  highValue: '#f59e0b',
  pushed: '#10b981',
  confirmed: '#8b5cf6',
};

export default function DailyTrendChart({
  data,
  title = '近30天内容趋势',
}: DailyTrendChartProps) {
  if (!data || data.length === 0) {
    return (
      <div className="p-8 text-center text-zinc-400 dark:text-[var(--text-muted)] text-sm font-sans">
        暂无趋势数据
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <h3 className="text-sm font-semibold text-zinc-700 dark:text-[var(--text-primary)] font-sans">
        {title}
      </h3>
      <ResponsiveContainer width="100%" height={260}>
        <AreaChart data={data} margin={{ top: 4, right: 16, bottom: 4, left: -8 }}>
          <defs>
            <linearGradient id="gradTotal" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor={COLORS.total} stopOpacity={0.25} />
              <stop offset="95%" stopColor={COLORS.total} stopOpacity={0} />
            </linearGradient>
            <linearGradient id="gradHigh" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor={COLORS.highValue} stopOpacity={0.25} />
              <stop offset="95%" stopColor={COLORS.highValue} stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="currentColor" className="text-zinc-200 dark:text-zinc-700" />
          <XAxis
            dataKey="date"
            tick={{ fontSize: 11, fontFamily: 'sans-serif' }}
            tickFormatter={(val) => val.slice(5)}
            stroke="currentColor"
            className="text-zinc-400 dark:text-zinc-500"
          />
          <YAxis tick={{ fontSize: 11, fontFamily: 'sans-serif' }} stroke="currentColor" />
          <Tooltip
            contentStyle={{
              backgroundColor: 'var(--surface, #fff)',
              border: '1px solid var(--surface-border, #e5e7eb)',
              borderRadius: '0.5rem',
              fontSize: '12px',
              fontFamily: 'sans-serif',
              color: 'var(--text-primary, #18181b)',
            }}
            formatter={(value: number, name: string) => {
              const labels: Record<string, string> = {
                total: '总量',
                highValue: '高价值',
                pushed: '已推送',
                confirmed: '已确认',
              };
              return [value, labels[name] || name];
            }}
          />
          <Area
            type="monotone"
            dataKey="total"
            stroke={COLORS.total}
            fill="url(#gradTotal)"
            strokeWidth={2}
            name="总量"
          />
          <Area
            type="monotone"
            dataKey="highValue"
            stroke={COLORS.highValue}
            fill="url(#gradHigh)"
            strokeWidth={2}
            name="高价值"
          />
          <Area
            type="monotone"
            dataKey="pushed"
            stroke={COLORS.pushed}
            fill="none"
            strokeWidth={1.5}
            dot={false}
            name="已推送"
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
