import assert from 'node:assert/strict';
import { buildResearchJobsPollEvent } from './SSEPollingModel';

const jobs = [
  { id: '1', status: 'processing' },
  { id: '2', status: 'completed' },
];

const event = buildResearchJobsPollEvent({ items: jobs });

assert.equal(event.type, 'research_jobs.poll');
assert.deepEqual(event.payload.items, jobs);
