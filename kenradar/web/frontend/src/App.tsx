/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
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
import DetailView from './components/DetailView';

export default function App() {
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
    generateWeeklyBrief
  } = useAppState();

  if (isInitializing) {
    return (
      <div className="flex items-center justify-center h-screen bg-[#F5F5F7] text-zinc-900 font-sans">
        <div className="text-center space-y-4">
          <div className="w-10 h-10 border-4 border-zinc-250 border-t-black rounded-full animate-spin mx-auto"></div>
          <p className="text-xs tracking-widest uppercase font-mono text-zinc-500">正在载入 KenRadar 知识数据库...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#F5F5F7] flex flex-col lg:flex-row">
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

            {(currentPage === 'run' || currentPage === 'publish') && (
              <RunCenter
                key={currentPage}
                videos={videos}
                tasks={tasks}
                retryStage={retryStage}
                bulkRetryFailed={bulkRetryFailed}
                navigateTo={navigateTo}
                pushRecords={pushRecords}
                logs={logs}
                alerts={alerts}
                system={system}
                config={config}
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
          </>
        )}

      </main>
    </div>
  );
}
