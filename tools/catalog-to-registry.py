#!/usr/bin/env python3
"""Build a products CSV (insurance-data-api products:import header) from catalog.csv.

Usage: python3 catalog-to-registry.py <repo-dir> <existing-registry.csv> <out.csv> <catalog-sha>

Rules (agreed with Squad A, 2026-11-14):
- Only rows with tag_status=complete and a UIN.
- Never a UIN already in the existing registry (the importer would overwrite its curated name).
- One row per UIN: the name seen most often across that UIN's documents; ties go to the wording/CIS name.
- Status is always 'unknown'; notes say extracted_unverified and cite the catalog commit.
- Travel and non-health/non-life categories are out of scope and skipped.
"""
import collections
import csv
import re
import sys
import urllib.parse

REPO, EXISTING, OUT, SHA = sys.argv[1:5]
UIN_PATTERN = re.compile(r'^[A-Z0-9][A-Z0-9/-]{8,29}$')
LINE = {
    'health_individual': 'health_indemnity', 'health_group': 'group_health', 'health_addon': 'add_on',
    'critical_illness': 'critical_illness', 'personal_accident': 'personal_accident',
    'life_term': 'term', 'life_health': 'life_health',
    'life_savings': 'life_other', 'life_ulip': 'life_other', 'life_pension': 'life_other', 'life_child': 'life_other',
    'life_group': 'life_other', 'life_rider': 'life_other', 'life_other': 'life_other',
}
DOC_COL = {'wording': 'wording_url', 'cis': 'cis_url', 'prospectus': 'prospectus_url', 'brochure': 'brochure_url'}
PREFER = {'wording': 0, 'cis': 1, 'prospectus': 2, 'brochure': 3}

DOC_SUFFIX = re.compile(r'[\s_\-–(]*(t\s*&\s*c|terms?\s*(and|&)\s*conditions?|surrender value factors?|policy\s*doc\w*|policy\s*wordings?|brochure|prospectus|cis|sales\s*lit\w*|leaflet|benefit illustration|rate chart|final|revised|new)[\s)]*$', re.I)
BAD_NAME = re.compile(r'^an? (unit|non|individual|group|traditional)|reg\.? ?no|\bcin\b|members under|^insurance[- ]plans?$|^(canara hsbc|hdfc|icici|tata aia|sbi|kotak|axis max|max)[\w ]*(life )?insurance( company)?( limited)?$|<<|\bsub\s*:|policy\s*no\b|appendix|annexure|\bdear\b|\b(\w+) \1 \1\b|schedule of|identification|solicitation|subject matter|investment risk|plan today|^insurance policy$|^policy$|^\W*$', re.I)


PRODUCT_WORD = re.compile(r'plan|polic|insurance|cover|shield|protect|raksha|assur|guarant|wealth|income|pension|term|care|health|saving|ulip|fortune|bima|suraksha|smart|secure|kavach|rider|benefit|scheme|life|sanchay|invest|retire|gratuity|superannuation|maxima|mediclaim|arogya|accident|optima|elevate|activ|star|navi', re.I)


def clean_name(n, uin):
    n = re.sub(re.escape(uin), ' ', n or '', flags=re.I)
    n = re.sub(r'\d{3}[A-Z]\d{3}V\d{2}|[A-Z]{6,10}\d{5}V\d{6}', ' ', n)
    n = re.sub(r'[_]+', ' ', n)
    n = re.sub(r'\.(cdr|pdf|docx?|indd|ai)\b', ' ', n, flags=re.I)                       # file extensions in titles
    n = re.sub(r'^\s*(policy\s*(document|wordings?|bond)|brochure|prospectus)\s+(for|of)\s+', '', n, flags=re.I)
    n = re.sub(r'[-–\s]+(brochure|prospectus|policy\s*(bond|document|wordings?)|offline|online|v\s*\d+(\.\d+)*)\b.*$', '', n, flags=re.I)
    n = re.sub(r'^\s*(product\s*name|name of the (product|plan|policy)|policy\s*document|plan\s*name)\s*[:\-–]\s*', '', n, flags=re.I)
    n = n.replace('>', ' ').replace('<', ' ')
    for _ in range(3):
        n = DOC_SUFFIX.sub('', n).strip(' -–_,.:()')
    n = re.sub(r'\s+', ' ', n).strip()
    if re.fullmatch(r'[a-z0-9]+(-[a-z0-9]+)+', n):
        n = n.replace('-', ' ').title()
    words = re.findall(r'[A-Za-z]{2,}', n)
    if BAD_NAME.search(n) or len(words) < 2 or len(words) > 10 or len(n) > 80:
        return ''
    if n.isupper() and len(words) > 4:
        return ''
    if n[:1].islower() or re.search(r'\b(\w+) \1\b|policyholder|schedule|modified view|demands|factors|rates\b|^policy term$|provisions|promises ka partner|enriching lives|^a market|merged|\.\s+\w', n, re.I):
        return ''
    if not PRODUCT_WORD.search(n):
        return ''
    return n


norm = lambda u: re.sub(r'\s+', '', u or '').upper()
existing = {norm(r['uin']) for r in csv.DictReader(open(EXISTING))}
groups = collections.defaultdict(list)
for r in csv.DictReader(open(f'{REPO}/catalog.csv')):
    u = norm(r['uin'])
    if r['tag_status'] != 'complete' or not u or u in existing or not UIN_PATTERN.match(u) or r['category'] not in LINE:
        continue
    groups[u].append(r)

cols = ['uin', 'product_name', 'insurer_legal_name', 'insurer_website', 'line', 'status', 'version', 'wording_url',
        'cis_url', 'prospectus_url', 'brochure_url', 'source_url', 'fetched_at', 'notes']
out, conflicts, no_name = [], 0, 0
for u, rs in sorted(groups.items()):
    for r in rs:
        r['product_name'] = clean_name(r['product_name'], u)
    names = collections.Counter(r['product_name'] for r in rs if r['product_name'])
    if not names:
        no_name += 1
        continue
    top = names.most_common()
    best = top[0][1]
    tied = [n for n, c in top if c == best]
    name = min(tied, key=lambda n: min(PREFER.get(r['doc_type'], 9) for r in rs if r['product_name'] == n))
    insurers = {r['insurer_legal_name'] for r in rs}
    if len(insurers) > 1:
        conflicts += 1
        continue
    lines = collections.Counter(LINE[r['category']] for r in rs).most_common(1)[0][0]
    row = dict.fromkeys(cols, '')
    host = urllib.parse.urlparse(rs[0]['source_url']).netloc
    v = re.search(r'V(\d{2})$', u) or re.search(r'V(\d{2})\d{4}$', u)
    row.update(uin=u, product_name=name, insurer_legal_name=insurers.pop(), insurer_website=f'https://{host}' if host else '',
               line=lines, status='unknown', version=f'V{v.group(1)}' if v else '', source_url=rs[0]['source_url'],
               fetched_at='2026-11-14',
               notes=f'extracted_unverified; source=insurance-raw-docs catalog {SHA}; {len(rs)} docs; name variants {len(names)}')
    for r in sorted(rs, key=lambda r: PREFER.get(r['doc_type'], 9)):
        c = DOC_COL.get(r['doc_type'])
        if c and not row[c]:
            row[c] = r['source_url']
    out.append(row)

with open(OUT, 'w', newline='') as f:
    w = csv.DictWriter(f, fieldnames=cols)
    w.writeheader()
    w.writerows(out)
print({'products': len(out), 'skipped_multi_insurer_uin': conflicts, 'skipped_no_clean_name': no_name,
       'by_line': dict(collections.Counter(r['line'] for r in out))})
