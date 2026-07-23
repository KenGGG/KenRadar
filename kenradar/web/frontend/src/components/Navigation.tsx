/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React, { useState } from 'react';
import {
  Radar,
  Cpu,
  Activity,
  SlidersHorizontal,
  Menu,
  X,
  Tv,
  Moon,
  Sun,
  BarChart3,
} from 'lucide-react';
import { VideoContent, ResearchTask, SystemInfo } from '../types';
import { useTheme } from '../hooks/useTheme';

interface NavigationProps {
  currentPage: string;
  selectedVideoId: string | null;
  navigateTo: (page: string, id: string | null) => void;
  videos: VideoContent[];
  tasks: ResearchTask[];
  system: SystemInfo;
}

export default function Navigation({ 
  currentPage, 
  selectedVideoId, 
  navigateTo, 
  videos, 
  tasks,
  system
}: NavigationProps) {
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);
  const { theme, toggleTheme } = useTheme();

  // Derive counts
  const failedTasksCount = videos.filter(v => v.status === 'failed').length;
  const runningTasksCount = tasks.filter(t => t.status === 'processing').length;
  const alertCount = Number(system.health?.alert_attention || 0);
  const attentionCount = Math.max(failedTasksCount, alertCount);
  const gpuPercent = system.gpu_percent ?? 0;

  const navItems = [
    { id: 'radar', name: '监控首页', icon: Radar, count: 0 },
    { id: 'sources', name: '来源管理', icon: Tv, count: 0 },
    { id: 'insights', name: '来源洞察', icon: BarChart3, count: 0 },
    { id: 'research', name: '博主研究', icon: Cpu, count: runningTasksCount },
    { id: 'run', name: '处理中心', icon: Activity, count: attentionCount },
    { id: 'config', name: '系统设置', icon: SlidersHorizontal, count: 0 },
  ];

  const handleNavClick = (id: string) => {
    navigateTo(id, null);
    setIsMobileMenuOpen(false);
  };

  return (
    <>
      {/* Mobile Top Header Banner */}
      <header className="lg:hidden flex items-center justify-between px-4 py-3 sticky top-0 z-50 border-b text-zinc-900" style={{ backgroundColor: 'var(--surface)', borderColor: 'var(--surface-border)' }}>
        <div className="flex items-center space-x-2.5 cursor-pointer" onClick={() => handleNavClick('radar')}>
          <div className="p-1.5 bg-black rounded-lg text-white flex items-center justify-center">
            <Radar className="w-5 h-5" />
          </div>
          <span className="font-sans font-bold text-lg tracking-tight text-zinc-900 dark:text-[var(--text-primary)]">KenRadar <span className="text-blue-600 dark:text-[var(--accent)] font-semibold text-sm">v2</span></span>
        </div>
        <button 
          id="mobile_menu_toggle_btn"
          onClick={() => setIsMobileMenuOpen(!isMobileMenuOpen)}
          className="p-2 text-zinc-500 hover:text-zinc-900 outline-none w-11 h-11 flex items-center justify-center transition"
          aria-label="Toggle navigation menu"
        >
          {isMobileMenuOpen ? <X className="w-6 h-6" /> : <Menu className="w-6 h-6" />}
        </button>
      </header>

      {/* Desktop Sidebar Panel */}
      <aside className="hidden lg:flex flex-col w-60 h-screen sticky top-0 select-none" style={{ backgroundColor: 'var(--surface)', borderRightColor: 'var(--surface-border)', color: 'var(--text-primary)' }}>
        {/* Top Branding Header */}
        <div className="p-6 flex items-center space-x-3 cursor-pointer" onClick={() => handleNavClick('radar')}>
          <div className="w-8 h-8 bg-black rounded-lg flex items-center justify-center">
            <Radar className="w-4 h-4 text-white" />
          </div>
          <span className="font-bold tracking-tight text-lg text-zinc-900 dark:text-[var(--text-primary)]">KenRadar <span className="text-blue-600 dark:text-[var(--accent)]">v2</span></span>
        </div>

        {/* Navigation Core Menu Nodes */}
        <nav className="flex-1 px-4 py-4 space-y-1">
          <div className="text-[10px] uppercase tracking-widest font-bold mb-2.5 px-3" style={{ color: 'var(--text-muted)' }}>核心流程</div>
          {navItems.map((item) => {
            const Icon = item.icon;
            const isActive = currentPage === item.id && !selectedVideoId;
            return (
              <button
                key={item.id}
                id={`nav_btn_${item.id}`}
                onClick={() => handleNavClick(item.id)}
                className={`w-full flex items-center justify-between px-3 py-2 rounded-lg font-sans text-sm font-medium transition-colors duration-150 ${
                  isActive
                    ? 'bg-blue-50 dark:bg-[var(--info-bg)] text-blue-700 dark:text-[var(--info)] font-semibold'
                    : ''
                }`}
                style={{ color: isActive ? undefined : 'var(--text-secondary)' }}
              >
                <div className="flex items-center space-x-3">
                  <Icon className={`w-4 h-4 ${isActive ? 'text-blue-600 dark:text-[var(--accent)]' : 'text-zinc-450 dark:text-[var(--text-muted)]'}`} />
                  <span>{item.name}</span>
                </div>
                {item.count > 0 && (
                  <span className={`text-[10px] font-mono px-1.5 py-0.5 rounded-full font-bold ${
                    item.id === 'run' 
                      ? (isActive ? 'bg-red-200 dark:bg-red-900/30 text-red-800 dark:text-red-300' : 'bg-red-50 dark:bg-[var(--danger-bg)] text-red-600 dark:text-[var(--danger)] border border-red-100 dark:border-[var(--danger-border)]')
                      : (isActive ? 'bg-blue-200 dark:bg-blue-900/30 text-blue-850 dark:text-blue-200' : 'bg-zinc-100 dark:bg-[var(--surface-muted)] text-zinc-550 dark:text-[var(--text-muted)]')
                  }`}>
                    {item.count}
                  </span>
                )}
              </button>
            );
          })}
        </nav>

        {/* Lower Sidebar System Health Summary Card */}
        <div className="p-4 m-4 rounded-xl" style={{ backgroundColor: 'var(--surface-muted)', borderColor: 'var(--surface-border)' }}>
          <div className="flex items-center justify-between mb-2">
            <span className="text-[11px] font-bold" style={{ color: 'var(--text-secondary)' }}>GPU 调度</span>
            <span className={`text-[11px] font-bold ${system.gpu_status === 'Active' ? 'text-green-600' : ''}`} style={{ color: system.gpu_status === 'Active' ? undefined : 'var(--text-muted)' }}>{system.gpu_status}</span>
          </div>
          <div className="h-1.5 w-full rounded-full overflow-hidden" style={{ backgroundColor: 'var(--surface-border)' }}>
            <div className="h-full bg-green-500" style={{ width: `${Math.max(0, Math.min(100, gpuPercent))}%` }}></div>
          </div>
          <div className="mt-2 text-[10px]" style={{ color: 'var(--text-muted)' }}>{system.gpu_label || 'GPU 调度'} · {gpuPercent}%</div>
        </div>

        {/* Dark mode toggle */}
        <div className="px-6 pb-4">
          <button
            type="button"
            onClick={toggleTheme}
            className="flex items-center justify-center gap-2 w-full rounded-lg px-3 py-2 text-xs font-medium transition"
            style={{ border: '1px solid var(--surface-border)', backgroundColor: 'var(--surface)', color: 'var(--text-secondary)' }}
            aria-label={`切换到${theme === 'light' ? '深色' : '浅色'}模式`}
          >
            {theme === 'light' ? (
              <>
                <Moon className="w-3.5 h-3.5" />
                <span>深色模式</span>
              </>
            ) : (
              <>
                <Sun className="w-3.5 h-3.5" />
                <span>浅色模式</span>
              </>
            )}
          </button>
        </div>
      </aside>

      {/* Mobile Drawer Slide Panel overlay */}
      {isMobileMenuOpen && (
        <div 
          id="mobile_drawer_overlay"
          className="lg:hidden fixed inset-0 bg-black/40 backdrop-blur-xs z-40 transition-opacity duration-200"
          onClick={() => setIsMobileMenuOpen(false)}
        >
          <div 
            id="mobile_drawer_content"
            className="w-72 h-screen border-r flex flex-col p-6 space-y-6"
            style={{ backgroundColor: 'var(--surface)', borderRightColor: 'var(--surface-border)', color: 'var(--text-primary)' }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between pb-4" style={{ borderBottom: '1px solid var(--surface-border)' }}>
              <div className="flex items-center space-x-3">
                <div className="p-1.5 bg-black rounded-lg text-white">
                  <Radar className="w-5 h-5" />
                </div>
                <span className="font-sans font-extrabold text-lg tracking-tight text-zinc-900">KenRadar <span className="text-blue-600">v2</span></span>
              </div>
              <button 
                id="drawer_close_btn"
                onClick={() => setIsMobileMenuOpen(false)}
                className="p-1.5 text-zinc-400 hover:text-zinc-900 outline-none w-10 h-10 flex items-center justify-center transition"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <nav className="flex-1 space-y-1">
              <div className="text-[10px] uppercase tracking-widest font-bold px-3 mb-2" style={{ color: 'var(--text-muted)' }}>核心流程</div>
              {navItems.map((item) => {
                const Icon = item.icon;
                const isActive = currentPage === item.id && !selectedVideoId;
                return (
                  <button
                    key={item.id}
                    id={`mobile_nav_btn_${item.id}`}
                    onClick={() => handleNavClick(item.id)}
                    className={`w-full flex items-center justify-between px-3 py-2.5 rounded-lg font-sans text-sm font-semibold transition ${
                      isActive 
                        ? 'bg-blue-50 dark:bg-[var(--info-bg)] text-blue-700 dark:text-[var(--info)]'
                        : 'text-zinc-650 hover:text-zinc-950 hover:bg-zinc-50'
                    }`}
                  >
                    <div className="flex items-center space-x-4">
                      <Icon className={`w-4 h-4 ${isActive ? 'text-blue-600' : 'text-zinc-400 dark:text-[var(--text-muted)]'}`} />
                      <span>{item.name}</span>
                    </div>
                    {item.count > 0 && (
                      <span className="text-[10px] font-mono px-2 py-0.5 rounded-full font-bold bg-zinc-100 dark:bg-[var(--surface-muted)] text-zinc-650 dark:text-[var(--text-secondary)] font-bold">
                        {item.count}
                      </span>
                    )}
                  </button>
                );
              })}
            </nav>

            <div className="pt-4 font-mono text-xs space-y-1.5" style={{ borderTop: '1px solid var(--surface-border)', color: 'var(--text-muted)' }}>
              <div className="flex justify-between">
                <span>SYSTEM PORT</span>
                <span>{system.port}</span>
              </div>
              <div className="flex justify-between text-emerald-600 font-semibold font-sans">
                <span>STAGE MONITOR</span>
                <span>RUNNING</span>
              </div>
            </div>

            {/* Dark mode toggle (mobile) */}
            <div className="pt-4 border-t border-zinc-150">
              <button
                type="button"
                onClick={toggleTheme}
                className="flex items-center justify-center gap-2 w-full rounded-lg px-3 py-2 text-xs font-medium transition"
                style={{ border: '1px solid var(--surface-border)', backgroundColor: 'var(--surface)', color: 'var(--text-secondary)' }}
                aria-label={`切换到${theme === 'light' ? '深色' : '浅色'}模式`}
              >
                {theme === 'light' ? (
                  <>
                    <Moon className="w-3.5 h-3.5" />
                    <span>深色模式</span>
                  </>
                ) : (
                  <>
                    <Sun className="w-3.5 h-3.5" />
                    <span>浅色模式</span>
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
