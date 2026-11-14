#!/usr/bin/env python3
"""Extract insurer helpline numbers and e-mail addresses from the collected PDFs (free, deterministic).

Usage: python3 insurer-contacts.py <repo-dir> <out.csv>
Reads the first 3 pages of each PDF in manifest.jsonl. Keeps Indian toll-free (1800/1860 ...) and e-mail
addresses on the insurer's own domain. One row per (insurer, contact), with how many documents print it and
one example document + page. Values are extracted_unverified. Public document text only.
"""
import collections, csv, json, os, re, signal, sys, urllib.parse
from pypdf import PdfReader

REPO, OUT = sys.argv[1:3]
TOLL = re.compile(r'\b(1[89]00|1860)[\s\-]?(\d{3})[\s\-]?(\d{3,4})\b')
MAIL = re.compile(r'\b[\w.+-]+@([\w-]+\.)+[a-z]{2,}\b', re.I)
CTX = re.compile(r'claim|toll|helpline|customer|call|care|grievance|service', re.I)


def alarm(*_):
    raise TimeoutError


signal.signal(signal.SIGALRM, alarm)
hits = collections.defaultdict(lambda: {'docs': set(), 'claim_ctx': 0, 'example': None})
for line in open(os.path.join(REPO, 'manifest.jsonl')):
    m = json.loads(line)
    host = urllib.parse.urlparse(m['source_url']).netloc.lower().removeprefix('www.')
    root = '.'.join(host.split('.')[-2:])
    try:
        signal.alarm(15)
        r = PdfReader(os.path.join(REPO, 'docs', m['path']))
        if r.is_encrypted:
            r.decrypt('')
        pages = [(i + 1, p.extract_text() or '') for i, p in enumerate(r.pages[:3])]
    except Exception:
        continue
    finally:
        signal.alarm(0)
    for pno, t in pages:
        for line_t in t.splitlines():
            found = [('phone', '-'.join(g)) for g in TOLL.findall(line_t)]
            found += [('email', e.group(0).lower()) for e in MAIL.finditer(line_t) if e.group(0).lower().endswith(root)]
            for kind, val in found:
                h = hits[(m['insurer_legal_name'], kind, val)]
                h['docs'].add(m['sha256'])
                h['claim_ctx'] += bool(CTX.search(line_t))
                h['example'] = h['example'] or (m['sha256'], pno, line_t.strip()[:120])
rows = []
for (ins, kind, val), h in hits.items():
    if len(h['docs']) < 2:
        continue
    rows.append({'insurer_legal_name': ins, 'kind': kind, 'value': val, 'documents': len(h['docs']),
                 'context_lines': h['claim_ctx'], 'example_sha256': h['example'][0], 'example_page': h['example'][1],
                 'example_line': h['example'][2], 'verification': 'extracted_unverified'})
rows.sort(key=lambda r: (r['insurer_legal_name'], -r['documents']))
with open(OUT, 'w', newline='') as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0]))
    w.writeheader(); w.writerows(rows)
print({'contacts': len(rows), 'insurers': len({r['insurer_legal_name'] for r in rows})})
