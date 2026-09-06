import assert from 'node:assert/strict';
import { V2_NAV } from './Navigation';

assert.deepEqual(V2_NAV.map(item => item.id), ['radar', 'sources', 'process-url', 'library', 'batches', 'system']);
console.log('NavigationModel tests passed');
