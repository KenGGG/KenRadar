// Local preview only: index precisely the hash-verified HTML allowlist.
import * as fs from 'node:fs/promises';
import path from 'node:path';
import { createHash } from 'node:crypto';
import * as pagefind from 'pagefind';

const [sourceArgument, manifestArgument, outputArgument] = process.argv.slice(2);
if (!sourceArgument || !manifestArgument || !outputArgument) throw new Error('source, manifest, output are required');
const source = await fs.realpath(sourceArgument);
const output = path.resolve(outputArgument);
const manifest = JSON.parse(await fs.readFile(manifestArgument, 'utf8'));
if (manifest.format !== 'kenradar-public-preview/1' || !Array.isArray(manifest.files)) throw new Error('Invalid allowlist');
const prepared = [];
const seen = new Set();
for (const entry of manifest.files) {
  if (typeof entry.path !== 'string' || path.isAbsolute(entry.path) || entry.path.split(/[\\/]/).some(part => part === '..') || !entry.path.endsWith('.html') || entry.path === 'index.html' || seen.has(entry.path)) throw new Error('Invalid public HTML path');
  const file = await fs.realpath(path.join(source, entry.path));
  if (path.relative(source, file).startsWith('..') || path.isAbsolute(path.relative(source, file))) throw new Error('Source escapes allowlist root');
  const bytes = await fs.readFile(file);
  if (createHash('sha256').update(bytes).digest('hex') !== entry.sha256) throw new Error('Public HTML hash mismatch');
  const content = bytes.toString('utf8');
  if (!/<html\b[^>]*\blang\s*=\s*["']zh(?:-CN)?["']/i.test(content)) throw new Error('Chinese page language must be explicit');
  prepared.push({path: entry.path, content});
  seen.add(entry.path);
}
// Exclusive destination: changed public scope always gets a fresh index.
await fs.mkdir(output, {recursive:false});
try {
  const built = await pagefind.createIndex({forceLanguage:'zh',writePlayground:false});
  if (built.errors.length || !built.index) throw new Error('Pagefind index creation failed');
  for (const entry of prepared) {
    await fs.mkdir(path.dirname(path.join(output,entry.path)), {recursive:true});
    await fs.writeFile(path.join(output,entry.path),entry.content,{flag:'wx'});
    const result = await built.index.addHTMLFile({url:'./'+entry.path, content:entry.content});
    if (result.errors.length) throw new Error('Pagefind HTML indexing failed');
  }
  const written = await built.index.writeFiles({outputPath:path.join(output,'pagefind')});
  if (written.errors.length) throw new Error('Pagefind bundle failed');
  const html = '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>KenRadar 公共搜索隔离预览</title><link href="./pagefind/pagefind-ui.css" rel="stylesheet"><body style="max-width:900px;margin:40px auto;padding:20px"><h1>公共搜索隔离预览</h1><p>此预览只包含明确列入 allowlist 的页面，未发布到互联网。</p><div id="search"></div><script src="./pagefind/pagefind-ui.js"></script><script>new PagefindUI({element:"#search",showSubResults:true});</script></body></html>';
  await fs.writeFile(path.join(output,'index.html'),html,{flag:'wx'});
  await fs.writeFile(path.join(output,'preview.manifest.json'),JSON.stringify({format:manifest.format,files:manifest.files,indexed_pages:prepared.length,network_publish:false},null,2),{flag:'wx'});
  console.log(JSON.stringify({indexed_pages:prepared.length,output,network_publish:false}));
} finally { await pagefind.close(); }
