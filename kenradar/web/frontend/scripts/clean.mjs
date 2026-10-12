import { rm } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';

// Fixed paths relative to this script, independent of shell working directory.
for (const name of ['dist', 'server.js']) {
  await rm(fileURLToPath(new URL(`../${name}`, import.meta.url)), { recursive: true, force: true });
}
