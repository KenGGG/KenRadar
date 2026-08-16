export interface ResearchJobsPollEvent {
  type: 'research_jobs.poll';
  payload: { items: Array<Record<string, any>> };
}

export function buildResearchJobsPollEvent(data: Record<string, any>): ResearchJobsPollEvent {
  return {
    type: 'research_jobs.poll',
    payload: { items: Array.isArray(data.items) ? data.items : [] },
  };
}
