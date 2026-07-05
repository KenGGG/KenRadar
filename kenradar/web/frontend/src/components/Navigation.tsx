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
  Send
} from 'lucide-react';
import { VideoContent, ResearchTask, SystemInfo } from '../types';

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

  // Derive counts
  const failedTasksCount = videos.filter(v => v.status === 'failed').length;
  const runningTasksCount = tasks.filter(t => t.status === 'processing').length;
  const alertCount = Number(system.health?.alert_attention || 0);
  const attentionCount = Math.max(failedTasksCount, alertCount);
  const gpuPercent = system.gpu_percent ?? 0;

  const navItems = [
    { id: 'radar', name: '监控首页', icon: Radar, count: 0 },
    { id: 'sources', name: '来源管理', icon: Tv, count: 0 },
    { id: 'research', name: '博主研究', icon: Cpu, count: runningTasksCount },
    { id: 'run', name: '处理流水线', icon: Activity, count: attentionCount },
    { id: 'publish', name: '发布通知', icon: Send, count: 0 },
    { id: 'config', name: '系统设置', icon: SlidersHorizontal, count: 0 },
  ];

  const handleNavClick = (id: string) => {
    navigateTo(id, null);
    setIsMobileMenuOpen(false);
  };

  return (
    <>
      {/* Mobile Top Header Banner */}
      <header className="lg:hidden flex items-center justify-between px-4 py-3 bg-white border-b border-zinc-200 text-zinc-900 sticky top-0 z-50">
        <div className="flex items-center space-x-2.5 cursor-pointer" onClick={() => handleNavClick('radar')}>
          <div className="p-1.5 bg-black rounded-lg text-white flex items-center justify-center">
            <Radar className="w-5 h-5" />
          </div>
          <span className="font-sans font-bold text-lg tracking-tight text-zinc-900">KenRadar <span className="text-blue-600 font-semibold text-sm">v2</span></span>
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
      <aside className="hidden lg:flex flex-col w-60 bg-white border-r border-zinc-200 text-zinc-800 h-screen sticky top-0 select-none">
        {/* Top Branding Header */}
        <div className="p-6 flex items-center space-x-3 cursor-pointer" onClick={() => handleNavClick('radar')}>
          <div className="w-8 h-8 bg-black rounded-lg flex items-center justify-center">
            <Radar className="w-4 h-4 text-white" />
          </div>
          <span className="font-bold tracking-tight text-lg text-zinc-900">KenRadar <span className="text-blue-600">v2</span></span>
        </div>

        {/* Navigation Core Menu Nodes */}
        <nav className="flex-1 px-4 py-4 space-y-1">
          <div className="text-[10px] uppercase tracking-widest text-zinc-400 font-bold mb-2.5 px-3">核心流程</div>
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
                    ? 'bg-blue-50 text-blue-700 font-semibold' 
                    : 'text-zinc-650 hover:text-zinc-950 hover:bg-zinc-50'
                }`}
              >
                <div className="flex items-center space-x-3">
                  <Icon className={`w-4 h-4 ${isActive ? 'text-blue-600' : 'text-zinc-450'}`} />
                  <span>{item.name}</span>
                </div>
                {item.count > 0 && (
                  <span className={`text-[10px] font-mono px-1.5 py-0.5 rounded-full font-bold ${
                    item.id === 'run' 
                      ? (isActive ? 'bg-red-200 text-red-800' : 'bg-red-50 text-red-600 border border-red-100') 
                      : (isActive ? 'bg-blue-200 text-blue-850' : 'bg-zinc-100 text-zinc-550')
                  }`}>
                    {item.count}
                  </span>
                )}
              </button>
            );
          })}
        </nav>

        {/* Lower Sidebar System Health Summary Card */}
        <div className="p-4 bg-zinc-50 m-4 rounded-xl border border-zinc-150">
          <div className="flex items-center justify-between mb-2">
            <span className="text-[11px] font-bold text-zinc-500">GPU 调度</span>
            <span className={`text-[11px] font-bold ${system.gpu_status === 'Active' ? 'text-green-600' : 'text-zinc-500'}`}>{system.gpu_status}</span>
          </div>
          <div className="h-1.5 w-full bg-zinc-200 rounded-full overflow-hidden">
            <div className="h-full bg-green-500" style={{ width: `${Math.max(0, Math.min(100, gpuPercent))}%` }}></div>
          </div>
          <div className="mt-2 text-[10px] text-zinc-400">{system.gpu_label || 'GPU 调度'} · {gpuPercent}%</div>
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
            className="w-72 bg-white h-screen border-r border-zinc-200 flex flex-col p-6 space-y-6 text-zinc-800"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between pb-4 border-b border-zinc-150">
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
              <div className="text-[10px] uppercase tracking-widest text-zinc-450 font-bold px-3 mb-2">核心流程</div>
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
                        ? 'bg-blue-50 text-blue-700' 
                        : 'text-zinc-650 hover:text-zinc-950 hover:bg-zinc-50'
                    }`}
                  >
                    <div className="flex items-center space-x-4">
                      <Icon className={`w-4 h-4 ${isActive ? 'text-blue-600' : 'text-zinc-400'}`} />
                      <span>{item.name}</span>
                    </div>
                    {item.count > 0 && (
                      <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-zinc-100 text-zinc-650 font-bold">
                        {item.count}
                      </span>
                    )}
                  </button>
                );
              })}
            </nav>

            <div className="pt-4 border-t border-zinc-150 font-mono text-xs text-zinc-450 space-y-1.5">
              <div className="flex justify-between">
                <span>SYSTEM PORT</span>
                <span>{system.port}</span>
              </div>
              <div className="flex justify-between text-emerald-600 font-semibold font-sans">
                <span>STAGE MONITOR</span>
                <span>RUNNING</span>
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
