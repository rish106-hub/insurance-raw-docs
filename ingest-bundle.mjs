#!/usr/bin/env node
// Ingest a browser bundle (fss-bundle-<tag>.jsonl: one {url,page,status,b64} per line) into the store.
// One bundle file = one browser download, which avoids Chrome's multiple-download prompt.
// Usage: node ingest-bundle.mjs <bundle.jsonl> <store-dir> <insurer_legal_name>
import { createHash } from 'node:crypto';
import { appendFileSync, existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { createInterface } from 'node:readline';
import { createReadStream } from 'node:fs';

const [bundle, store, insurer] = process.argv.slice(2);
if (!bundle || !store || !insurer) { console.error('usage: ingest-bundle.mjs <bundle.jsonl> <store-dir> <insurer>'); process.exit(2); }
const manifestPath = join(store, 'manifest.jsonl');
const known = new Set(existsSync(manifestPath) ? readFileSync(manifestPath, 'utf8').split('\n').filter(Boolean).map((l) => JSON.parse(l).sha256) : []);
const tally = {};
for await (const line of createInterface({ input: createReadStream(bundle) })) {
  if (!line.trim()) continue;
  const r = JSON.parse(line);
  let outcome = `not_stored_${r.status}`;
  if (r.b64) {
    const buf = Buffer.from(r.b64, 'base64');
    if (buf.subarray(0, 4).toString('latin1') !== '%PDF') outcome = 'not_pdf';
    else {
      const sha = createHash('sha256').update(buf).digest('hex');
      if (known.has(sha)) outcome = 'duplicate';
      else {
        known.add(sha);
        const host = new URL(r.url).host;
        mkdirSync(join(store, host), { recursive: true });
        const rel = join(host, `${sha}.pdf`);
        writeFileSync(join(store, rel), buf);
        appendFileSync(manifestPath, JSON.stringify({
          sha256: sha, path: rel, bytes: buf.length, content_type: 'application/pdf',
          source_url: r.url, final_url: r.url, page_url: r.page ?? '', insurer_legal_name: insurer,
          uin: '', product_name: '', line: '', doc_type: 'unknown', fetched_at: new Date().toISOString(),
          collection_method: 'browser_download', robots_consulted: false, parsed: false,
        }) + '\n');
        outcome = 'stored';
      }
    }
  }
  appendFileSync(join(store, 'attempts.jsonl'), JSON.stringify({ url: r.url, host: new URL(r.url).host, outcome, status: r.status, method: 'browser_bundle', insurer_legal_name: insurer, fetched_at: new Date().toISOString() }) + '\n');
  tally[outcome] = (tally[outcome] ?? 0) + 1;
}
console.log(JSON.stringify(tally));
