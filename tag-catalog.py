#!/usr/bin/env python3
"""Build catalog.csv: one row per stored PDF with the must-have tags.

Must-haves per PDF: uin, insurer_legal_name, product_name, category, pdf (path in this repo + source URL).
Sources, in order of preference: manifest/link-page metadata -> URL/filename -> PDF text (first pages).
Every tag records where it came from. Values read from the PDF are extracted_unverified.

Usage: python3 -I tag-catalog.py <repo-dir>
Reads <repo-dir>/manifest.jsonl and <repo-dir>/docs/, writes catalog.csv, catalog.jsonl, untagged.csv.
"""
import collections
import csv
import json
import os
import re
import signal
import sys
import urllib.parse

from pypdf import PdfReader

REPO = sys.argv[1]
LIFE_INSURERS = re.compile(r'life|sud life|star union dai-ichi', re.I)

UIN_GENERAL = re.compile(r'\b([A-Z]{3,6}(?:HL|PA|TG|TI|TR|MI|GS|HE|LI|IP|MC|PE|FL|MR|OP|CI)[A-Z]{1,3}\d{5}V\d{6})\b')
UIN_GENERAL_LOOSE = re.compile(r'\b([A-Z]{6,10}\d{5}V\d{6})\b')
UIN_LIFE = re.compile(r'\b(\d{3}[A-Z]\d{3}V\d{2})\b')
UIN_OLD = re.compile(r'\b(IRDAI?/(?:NL-)?HLT/[A-Z0-9]+/[A-Z\-]+/V\.?[IVX]+/\d+/\d{2,4}-\d{2,4})\b')

GENERIC_NAMES = re.compile(r'^(download ?pdf|download now|download|view|click here|pdf|brochure|prospectus|policy wording[s]?|cis|customer information sheet|in case you are unable.*|.{0,2})$', re.I)
DOC_WORDS = re.compile(r'\b(policy|wordings?|brochure|prospectus|cis|customer information sheet|proposal form|sales|leaflet|web|final|new|revised|updated|v ?\d+(\.\d+)?|uin.*)\b', re.I)


class Timeout(Exception):
    pass


def _alarm(_s, _f):
    raise Timeout()


signal.signal(signal.SIGALRM, _alarm)


def pdf_text(path, pages=3):
    """First pages' text and the document title. Bounded by a timeout; failures return empty."""
    signal.alarm(20)
    try:
        r = PdfReader(path)
        title = ''
        try:
            title = (r.metadata.title or '') if r.metadata else ''
        except Exception:
            title = ''
        txt = []
        for p in r.pages[:pages]:
            try:
                txt.append(p.extract_text() or '')
            except Exception:
                pass
        return '\n'.join(txt), title
    except Exception:
        return '', ''
    finally:
        signal.alarm(0)


def find_uin(s):
    for rx in (UIN_GENERAL, UIN_LIFE, UIN_GENERAL_LOOSE, UIN_OLD):
        found = rx.findall(s or '')
        if found:
            return collections.Counter(found).most_common(1)[0][0]
    return ''


def name_from_url(url):
    base = urllib.parse.unquote(url.split('?')[0].rstrip('/').split('/')[-1])
    base = re.sub(r'\.(pdf|docx?)$', '', base, flags=re.I)
    base = re.sub(r'_[0-9a-f]{10}$', '', base)            # strapi hash suffix
    base = re.sub(r'-\d{6,}$|_\d{8,}$', '', base)           # timestamps
    base = re.sub(r'\d{3}[A-Z]\d{3}V\d{2}|[A-Z]{6,10}\d{5}V\d{6}', ' ', base)
    base = re.sub(r'[_\-+]+', ' ', base)
    base = DOC_WORDS.sub(' ', base)
    base = re.sub(r'\s+', ' ', base).strip(' .,-')
    return base


def name_from_text(text, uin):
    if uin:
        for line in text.splitlines():
            if uin in line.replace(' ', ''):
                cand = re.split(r'\(?\s*UIN|\bUIN\b', line, flags=re.I)[0].strip(' :-–,|(')
                cand = re.sub(r'^(product name|name of the (product|plan|policy))\s*[:\-]\s*', '', cand, flags=re.I)
                cand = cand.replace(uin, '').strip(' :-–,|(')
                if 4 <= len(cand) <= 90 and len(re.findall(r'[A-Za-z]{3,}', cand)) >= 2:
                    return cand
    for line in text.splitlines()[:25]:
        l = line.strip()
        if 6 <= len(l) <= 80 and re.search(r'(plan|policy|insurance|cover|shield|protect|bima|care|health)', l, re.I) \
                and not re.search(r'(limited|ltd|registered|irdai reg|cin|www\.|page \d)', l, re.I):
            return l
    return ''


def category(uin, name, insurer, doc_type):
    u = uin.upper()
    n = (name or '').lower()
    if re.search(r'rider', n) or re.match(r'^\d{3}B\d{3}V\d{2}$', u):
        return 'life_rider' if LIFE_INSURERS.search(insurer) else 'health_addon'
    if re.search(r'HL[IG]A|HLA', u) or re.search(r'add[\s-]?on', n):
        return 'health_addon'
    if 'HLGP' in u or 'HLGR' in u or (re.search(r'\bgroup\b', n) and re.search(r'health|hospi|medi|critical|opd', n)):
        return 'health_group'
    if re.search(r'PA[IG]P|PAIP', u) or re.search(r'accident|suraksha bima|trauma', n):
        return 'personal_accident'
    if re.search(r'T[IG][DOS]P|TR[IG]P', u) or re.search(r'travel', n):
        return 'travel'
    if re.search(r'critical|cancer|cardiac|heart|diabet', n):
        return 'critical_illness'
    if 'HLIP' in u or 'HLMI' in u or re.search(r'HL[A-Z]?P', u):
        return 'health_individual'
    if LIFE_INSURERS.search(insurer) or re.match(r'^\d{3}[A-Z]\d{3}V\d{2}$', u):
        if re.search(r'term|protect|shield|jeevan bima|saral jeevan|smart secure|click 2 protect|i ?protect|sampoorn|raksha', n):
            return 'life_term'
        if re.search(r'health|hospi|medi', n):
            return 'life_health'
        if re.search(r'pension|annuity|retire', n):
            return 'life_pension'
        if re.search(r'child|scholar|future star|young', n):
            return 'life_child'
        if re.search(r'ulip|wealth|fund|invest|linked', n) or re.match(r'^\d{3}L', u):
            return 'life_ulip'
        if re.match(r'^\d{3}G', u) or re.search(r'group', n):
            return 'life_group'
        if re.match(r'^\d{3}N', u) or re.search(r'saving|income|guarantee|endow|money ?back|bachat|platina|assure', n):
            return 'life_savings'
        return 'life_other'
    if re.search(r'health|medi|hospital|arogya|care|optima|surplus|top.?up|floater|family', n):
        return 'health_individual'
    if doc_type in ('claim_form', 'proposal_form'):
        return 'form_general'
    return ''


def main():
    rows = [json.loads(l) for l in open(os.path.join(REPO, 'manifest.jsonl')) if l.strip()]
    out = []
    for i, m in enumerate(rows):
        path = os.path.join(REPO, 'docs', m['path'])
        url = m.get('source_url', '')
        insurer = m.get('insurer_legal_name', '')
        uin, uin_src = (m.get('uin') or '').strip(), 'link_page'
        if uin and not (UIN_GENERAL_LOOSE.fullmatch(uin) or UIN_LIFE.fullmatch(uin) or UIN_OLD.fullmatch(uin)):
            uin = find_uin(uin)
        if not uin:
            uin, uin_src = find_uin(urllib.parse.unquote(url)), 'url'
        name = (m.get('product_name') or '').strip()
        name_src = 'link_page'
        if not name or GENERIC_NAMES.match(name) or len(name) > 100:
            name, name_src = '', ''
        text, title = ('', '')
        if (not uin or not name) and os.path.exists(path):
            text, title = pdf_text(path)
        if not uin and text:
            uin, uin_src = find_uin(text), 'pdf_text'
        if not name and text:
            name, name_src = name_from_text(text, uin), 'pdf_text'
        if not name and title and not GENERIC_NAMES.match(title) and len(title) < 100 and not re.search(r'microsoft|untitled|\.docx?$', title, re.I):
            name, name_src = title.strip(), 'pdf_title'
        if not name:
            name, name_src = name_from_url(url), 'url'
        if not uin:
            uin_src = ''
        cat = category(uin, name, insurer, m.get('doc_type', ''))
        missing = [k for k, v in (('uin', uin), ('insurer_legal_name', insurer), ('product_name', name), ('category', cat)) if not v]
        out.append({
            'sha256': m['sha256'], 'pdf_path': 'docs/' + m['path'], 'source_url': url,
            'insurer_legal_name': insurer, 'uin': uin, 'product_name': name, 'category': cat,
            'doc_type': m.get('doc_type', ''), 'uin_source': uin_src, 'name_source': name_src,
            'tag_status': 'complete' if not missing else 'missing:' + '|'.join(missing),
            'verification': 'extracted_unverified',
        })
        if i % 200 == 0:
            print(f'{i}/{len(rows)}', file=sys.stderr)
    # Inherit a UIN from a sibling document of the same insurer with the same product name.
    norm = lambda x: re.sub(r'[^a-z0-9]+', ' ', (x or '').lower()).strip()
    by_ins = collections.defaultdict(dict)
    for r in out:
        if r['uin'] and r['product_name']:
            by_ins[r['insurer_legal_name']].setdefault(norm(r['product_name']), r['uin'])
    for r in out:
        if r['uin'] or not r['product_name']:
            continue
        n = norm(r['product_name'])
        if len(n) < 6:
            continue
        hit = by_ins[r['insurer_legal_name']].get(n) or next((u for k, u in by_ins[r['insurer_legal_name']].items() if len(k) >= 8 and (k in n or n in k)), '')
        if hit:
            r['uin'], r['uin_source'] = hit, 'sibling_doc_same_product'
            if not r['category']:
                r['category'] = category(hit, r['product_name'], r['insurer_legal_name'], r['doc_type'])
        missing = [k for k in ('uin', 'insurer_legal_name', 'product_name', 'category') if not r[k]]
        r['tag_status'] = 'complete' if not missing else 'missing:' + '|'.join(missing)
    cols = list(out[0])
    with open(os.path.join(REPO, 'catalog.csv'), 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader(); w.writerows(out)
    with open(os.path.join(REPO, 'catalog.jsonl'), 'w') as f:
        for r in out:
            f.write(json.dumps(r) + '\n')
    with open(os.path.join(REPO, 'untagged.csv'), 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader(); w.writerows(r for r in out if r['tag_status'] != 'complete')
    c = collections.Counter(r['tag_status'] for r in out)
    print(json.dumps({'total': len(out), **c, 'categories': collections.Counter(r['category'] for r in out)}, default=dict))


main()
