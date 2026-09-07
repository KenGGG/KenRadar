/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 *
 * Extracted from App.tsx — the actual page rendering logic.
 * Wraps the theme provider so dark mode can toggle at the top level.
 */

import React from 'react';
import { useAppState } from './hooks/useAppState';
import Navigation from './components/Navigation';
import RadarDashboard from './components/RadarDashboard';
import ArchiveWorkspace from './components/ArchiveWorkspace';
import ResearchWorkspace from './components/ResearchWorkspace';
import SourceManager from './components/SourceManager';
import RunCenter from './components/RunCenter';
import ConfigEditor from './components/ConfigEditor';
import ProcessUrl from './components/ProcessUrl';
import DetailView from './components/DetailView';
import SourceInsights from './components/SourceInsights';

export default function AppContent() {
  const {
    currentPage,
    navigateTo,
    selectedVideoId,
    videos,
    libraryStats,
    tasks,
    sources,
    sourceCategories,
    pushRecords,
    logs,
    config,
    alerts,
    system,
    highValueThreshold,
    curationThresholds,
    notes,
    briefs,
    isInitializing,
    rebootWebUI,
    saveConfig,
    addSource,
    previewSource,
    checkSourceNow,
    updateSourceCategory,
    updateSourceCategoryOption,
    toggleSourceStatus,
    deleteSource,
    triggerManualScan,
    testLatest,
    runResearchTask,
    controlResearchTask,
    loadResearchJob,
    retryResearchFailed,
    retryStage,
    bulkRetryFailed,
    pushToFeishuManually,
    generateWeeklyBrief,
  } = useAppState();

  if (isInitializing) {
    return (
      <div className="flex items-center justify-center h-screen bg-[var(--background)] text-[var(--text-primary)] font-sans">
        <div className="text-center space-y-4">
          <div className="w-10 h-10 border-4 border-[var(--surface-border)] border-t-[var(--accent)] rounded-full animate-spin mx-auto"></div>
          <p className="text-xs tracking-widest uppercase font-mono text-[var(--text-secondary)]">正在载入 KenRadar 知识数据库...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[var(--background)] flex flex-col lg:flex-row">
      {/* Sidebar navigation */}
      <Navigation
        currentPage={currentPage}
        selectedVideoId={selectedVideoId}
        navigateTo={navigateTo}
        videos={videos}
        tasks={tasks}
        system={system}
      />

      {/* Main app panel wrapper */}
      <main className="flex-1 w-full max-w-[1600px] mx-auto p-4 md:p-8 overflow-y-auto">

        {/* Render pages depending on active states */}
        {selectedVideoId ? (
          <DetailView
            videoId={selectedVideoId}
            videos={videos}
            navigateTo={navigateTo}
            retryStage={retryStage}
            pushToFeishuManually={pushToFeishuManually}
            highValueThreshold={curationThresholds.high_value_threshold}
          />
        ) : (
          <>
            {currentPage === 'radar' && (
              <RadarDashboard
                videos={videos}
                tasks={tasks}
                sources={sources}
                navigateTo={navigateTo}
                triggerManualScan={triggerManualScan}
                testLatest={testLatest}
                loading={isInitializing}
                highValueThreshold={highValueThreshold}
              />
            )}

            {currentPage === 'archive' && (
              <ArchiveWorkspace
                videos={videos}
                libraryStats={libraryStats}
                navigateTo={navigateTo}
                pushToFeishuManually={pushToFeishuManually}
                generateWeeklyBrief={generateWeeklyBrief}
                notes={notes}
                briefs={briefs}
                highValueThreshold={curationThresholds.high_value_threshold}
                recommendationThreshold={curationThresholds.push_threshold}
              />
            )}

            {currentPage === 'research' && (
              <ResearchWorkspace
                videos={videos}
                tasks={tasks}
                runResearchTask={runResearchTask}
                controlResearchTask={controlResearchTask}
                loadResearchJob={loadResearchJob}
                retryResearchFailed={retryResearchFailed}
                briefs={briefs}
              />
            )}

            {currentPage === 'sources' && (
              <SourceManager
                sources={sources}
                sourceCategories={sourceCategories}
                addSource={addSource}
                previewSource={previewSource}
                checkSourceNow={checkSourceNow}
                updateSourceCategory={updateSourceCategory}
                updateSourceCategoryOption={updateSourceCategoryOption}
                toggleSourceStatus={toggleSourceStatus}
                deleteSource={deleteSource}
                runResearchTask={runResearchTask}
              />
            )}

            {currentPage === 'insights' && (
              <SourceInsights />
            )}

            {currentPage === 'run' && (
              <RunCenter
                videos={videos}
                pushRecords={pushRecords}
                logs={logs}
                alerts={alerts}
                system={system}
                rebootWebUI={rebootWebUI}
                triggerManualScan={triggerManualScan}
              />
            )}

            {currentPage === 'config' && (
              <ConfigEditor
                config={config}
                saveConfig={saveConfig}
              />
            )}

            {currentPage === 'process' && (
              <ProcessUrl />
            )}
          </>
        )}

      </main>
    </div>
  );
}
