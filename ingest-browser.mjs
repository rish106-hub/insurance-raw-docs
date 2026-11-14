#!/usr/bin/env node
// Move PDFs saved by the browser (fss-<tag>-NNNN.pdf + fss-map-<tag>.csv in a downloads folder)
// into the content-addressed store and append them to manifest.jsonl.
// Usage: node ingest-browser.mjs <downloads-dir> <tag> <store-dir> <insurer_legal_name> [links.csv]
// links.csv (optional) supplies uin/product_name/doc_type/source_url per url.
import { createHash } from 'node:crypto';
import { appendFileSync, existsSync, mkdirSync, readFileSync, renameSync, unlinkSync } from 'node:fs';
import { join } from 'node:path';

const [dlDir, tag, store, insurer, linksCsv] = process.argv.slice(2);
if (!dlDir || !tag || !store || !insurer) {
  console.error('usage: ingest-browser.mjs <downloads-dir> <tag> <store-dir> <insurer_legal_name> [links.csv]');
  process.exit(2);
}

function parseCsv(text) {
  const rows = []; let row = []; let f = ''; let q = false;
  for (let i = 0; i < text.length; i += 1) {
    const c = text[i];
    if (q) { if (c === '"' && text[i + 1] === '"') { f += '"'; i += 1; } else if (c === '"') q = false; else f += c; }
    else if (c === '"') q = true;
    else if (c === ',') { row.push(f); f = ''; }
    else if (c === '\n' || c === '\r') { if (c === '\r' && text[i + 1] === '\n') i += 1; row.push(f); f = ''; if (row.some(Boolean)) rows.push(row); row = []; }
    else f += c;
  }
  if (f || row.length) { row.push(f); if (row.some(Boolean)) rows.push(row); }
  const [h, ...b] = rows;
  return b.map((r) => Object.fromEntries(h.map((k, j) => [k.trim(), (r[j] ?? '').trim()])));
}

const meta = new Map();
if (linksCsv && existsSync(linksCsv)) for (const r of parseCsv(readFileSync(linksCsv, 'utf8'))) meta.set(r.url, r);
const map = parseCsv(readFileSync(join(dlDir, `fss-map-${tag}.csv`), 'utf8'));
const manifestPath = join(store, 'manifest.jsonl');
const known = new Set(existsSync(manifestPath) ? readFileSync(manifestPath, 'utf8').split('\n').filter(Boolean).map((l) => JSON.parse(l).sha256) : []);
const tally = {};
for (const r of map) {
  const file = join(dlDir, `fss-${tag}-${String(r.idx).padStart(4, '0')}.pdf`);
  let outcome;
  if (!existsSync(file)) outcome = r.status.startsWith('200') ? 'missing_file' : `not_stored_${r.status}`;
  else {
    const buf = readFileSync(file);
    const sha = createHash('sha256').update(buf).digest('hex');
    if (known.has(sha)) { outcome = 'duplicate'; unlinkSync(file); }
    else {
      known.add(sha);
      const host = new URL(r.url).host;
      mkdirSync(join(store, host), { recursive: true });
      const rel = join(host, `${sha}.pdf`);
      renameSync(file, join(store, rel));
      const m = meta.get(r.url) ?? {};
      appendFileSync(manifestPath, JSON.stringify({
        sha256: sha, path: rel, bytes: buf.length, content_type: 'application/pdf',
        source_url: r.url, final_url: r.url, page_url: m.source_url ?? r.page ?? '',
        insurer_legal_name: insurer, uin: m.uin ?? '', product_name: m.product_name ?? '',
        line: '', doc_type: m.doc_type ?? 'unknown', fetched_at: new Date().toISOString(),
        collection_method: 'browser_download', robots_consulted: false, parsed: false,
      }) + '\n');
      outcome = 'stored';
    }
  }
  appendFileSync(join(store, 'attempts.jsonl'), JSON.stringify({ url: r.url, host: new URL(r.url).host, outcome, status: r.status, method: 'browser_download', insurer_legal_name: insurer, fetched_at: new Date().toISOString() }) + '\n');
  tally[outcome] = (tally[outcome] ?? 0) + 1;
}
console.log(JSON.stringify(tally));
