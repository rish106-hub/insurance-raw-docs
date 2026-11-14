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

REPO = sys.argv[1] if len(sys.argv) > 1 else ""
LIFE_INSURERS = re.compile(r'life|sud life|star union dai-ichi', re.I)

UIN_GENERAL = re.compile(r'\b([A-Z]{3,6}(?:HL|PA|TG|TI|TR|MI|GS|HE|LI|IP|MC|PE|FL|MR|OP|CI)[A-Z]{1,3}\d{5}V\d{6})\b')
UIN_GENERAL_LOOSE = re.compile(r'\b([A-Z]{6,10}\d{5}V\d{6})\b')
UIN_LIFE = re.compile(r'\b(\d{3}[A-Z]\d{3}V\d{2})\b')
UIN_OLD = re.compile(r'\b(IRDAI?/(?:NL-)?HLT/[A-Z0-9]+/[A-Z\-]+/V\.?[IVX]+/\d+/\d{2,4}-\d{2,4})\b')

GENERIC_NAMES = re.compile(r'^(download ?pdf|download now|download|view|click here|pdf|brochure|prospectus|policy wording[s]?|cis|customer information sheet|in case you are unable.*|.{0,2})$', re.I)
LABEL_NAME = re.compile(r'(identification number|^uin\b|^(product|plan|policy) (name|no)\b|^name of the (product|plan|policy)\b|^product\s*:?$)', re.I)
DOC_TYPE_RX = [
    ('cis', r'\bcis\b|customer.?information'),
    ('wording', r'wording|policy.?doc|terms.?(and|&).?cond|policy.?contract|specimen|\bpw\b'),
    ('prospectus', r'prospectus'),
    ('brochure', r'brochure|leaflet|sales.?lit'),
    ('proposal_form', r'proposal'),
    ('claim_form', r'claim'),
    ('service_form', r'\bkyc\b|nach|mandate|nominat|assignment|revival|surrender|request|service|change.?of|declaration|form'),
    ('rate_chart', r'rate.?chart|premium.?(rate|chart|table)'),
    ('benefit_illustration', r'illustration'),
]


def doc_type_of(cur, url, name):
    if cur and cur not in ('unknown', 'other'):
        return cur
    s = (urllib.parse.unquote(url) + ' ' + (name or '')).lower()
    for t, rx in DOC_TYPE_RX:
        if re.search(rx, s):
            return t
    return cur or 'unknown'


def load_registry():
    p = os.path.join(REPO, 'links', 'registry-uin-names.csv')
    reg = collections.defaultdict(set)
    if os.path.exists(p):
        for r in csv.DictReader(open(p)):
            u = re.sub(r'\s+', '', r['uin']).upper()
            if u and r['registry_product_name'].strip():
                reg[u].add(r['registry_product_name'].strip())
    return {u: next(iter(n)) for u, n in reg.items() if len(n) == 1}


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
        if r.is_encrypted:
            try:
                r.decrypt('')
            except Exception:
                pass
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


UIN_LABELLED = re.compile(r'UIN\s*(?:No\.?|Number)?\s*[:\-–]?\s*([A-Z0-9]{3,6}[A-Z]{0,6}\d{3,5}V\d{2,6})', re.I)


def find_uin(s):
    """Simple form for short strings (link text, URL): most common match of the first pattern that hits."""
    for rx in (UIN_GENERAL, UIN_LIFE, UIN_LABELLED, UIN_GENERAL_LOOSE, UIN_OLD):
        found = rx.findall(s or '')
        if found:
            return collections.Counter(found).most_common(1)[0][0]
    return ''


def uin_base(u):
    """Product identity without the filing version: 101N084V29 -> 101N084, HDFHLIP21345V012021 -> HDFHLIP21345."""
    return re.sub(r'V\d{2}(\d{4})?$', '', u)


def pick_uin(text, rider_doc):
    """UIN for a long PDF text. Returns (uin, ambiguous).

    A long document mentions other UINs (riders it offers, plans it replaces, group variants). Rules:
    labelled UINs ("UIN: ...") beat bare matches; product UINs beat riders (life 'B', general add-on)
    unless the document is a rider; if two or more distinct products remain, return no UIN (never guess).
    Versions of the same product collapse; the most frequent version wins.
    """
    s = text or ''
    found = []
    for rx in (UIN_GENERAL, UIN_LIFE, UIN_GENERAL_LOOSE, UIN_OLD):
        found += rx.findall(s)
    if not found:
        return '', False
    labelled = [u.upper() for u in UIN_LABELLED.findall(s)]
    labelled = [u for u in labelled if u in found]
    pool = labelled or found
    if not rider_doc:
        products = [u for u in pool if not re.match(r'^\d{3}[BC]\d{3}V\d{2}$', u)]
        pool = products or pool
    bases = collections.Counter(uin_base(u) for u in pool)
    if len(bases) > 1:
        (b1, c1), (_, c2) = bases.most_common(2)
        if c1 < 3 * c2:          # no clear owner: one product must dominate 3:1 to be taken
            return '', True
        pool = [u for u in pool if uin_base(u) == b1]
    return collections.Counter(pool).most_common(1)[0][0], False


def name_from_url(url):
    return clean_filename(urllib.parse.unquote(url.split('?')[0].rstrip('/').split('/')[-1]))


def clean_filename(base):
    """A file-name-like string ("POS_Easy_Bima_Sales_Literature_Final.pdf") to a plain name ("POS Easy Bima")."""
    base = re.sub(r'\.(pdf|docx?)$', '', base, flags=re.I)
    base = re.sub(r'_[0-9a-f]{10}$', '', base)            # strapi hash suffix
    base = re.sub(r'-\d{6,}$|_\d{8,}$', '', base)           # timestamps
    base = re.sub(r'\d{3}[A-Z]\d{3}V\d{2}|[A-Z]{6,10}\d{5}V\d{6}', ' ', base, flags=re.I)
    base = re.sub(r'[_\-+]+', ' ', base)
    base = re.sub(r'\(\d+\)', ' ', base)                                            # "optima super(1)"
    base = re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', base)                                  # "PolicyWordings" -> "Policy Wordings"
    base = DOC_WORDS.sub(' ', base)
    # Leftover file-name noise: "cum literature", "Document(s)", "Final3", "lot 02", dates, versions, leading ids.
    base = re.sub(r'\b(standard )?documents?\b|\bcum\b|\bliteratur\w*|\bfinal\d*\b|\blot \d+\b|\bpdf\b', ' ', base, flags=re.I)
    base = re.sub(r'\b(policy )?bond\b|\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]* \d{4}\b', ' ', base, flags=re.I)
    base = re.sub(r'\b\d{1,2} \d{1,2} \d{4}\b|\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\d{2,4}\b|\bv\.?\d+(\.\d+)*\b', ' ', base, flags=re.I)
    base = re.sub(r'\b(web|bro|brochure|sales|ver)\b|\b20\d{2}\b', ' ', base, flags=re.I)
    base = re.sub(r'^\d{3,}\s+', '', base.strip())
    base = re.sub(r'\s+', ' ', base).strip(' .,-')
    return base


def name_from_text(text, uin):
    if uin:
        for line in text.splitlines():
            if uin in line.replace(' ', ''):
                cand = re.split(r'\(?\s*UIN|\bUIN\b', line, flags=re.I)[0].strip(' :-–,|(')
                cand = re.sub(r'^(product name|name of the (product|plan|policy))\s*[:\-]\s*', '', cand, flags=re.I)
                cand = cand.replace(uin, '').strip(' :-–,|(')
                if 4 <= len(cand) <= 90 and not LABEL_NAME.search(cand) and len(re.findall(r'[A-Za-z]{3,}', cand)) >= 2:
                    return cand
    for line in text.splitlines()[:25]:
        l = line.strip()
        if 6 <= len(l) <= 80 and not LABEL_NAME.search(l) and re.search(r'(plan|policy|insurance|cover|shield|protect|bima|care|health)', l, re.I) \
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
    if doc_type in ('claim_form', 'proposal_form', 'service_form'):
        return 'form_general'
    return ''


REGISTRY = {}


# Product-name junk: form placeholders, letters, registration lines, insurer-only names, generic doc words and
# sentence fragments. A junk candidate is skipped so the next source (PDF text, title, URL, a sibling with the
# same UIN) can supply the name; if every source is junk the name stays blank (never a guess).
JUNK_NAME = re.compile(
    r'<<|>>|«|»|policy ?holder|identification number|^sub\s*:|policy no\.?\s*\d|\birdai? reg|\bcin\s*[:\-]|^part [a-z]\s*[:\-]'
    r'|your policy details|branch representative|^welcome to|promises ka partner|^dear\b|^in this policy|unless the context'
    r'|^page \d|^table of contents|^contents$|^annexure\b|^schedule of\b|^(the )?list of\b'
    r'|toll ?free|\b1[86]00[\s-]?\d|@|e-?mail\s*:|\?\s*$|^(and|or|of|to|for|with|by|from)\b|\bcopy\s*$', re.I)
GENERIC_WORDS = {'policy', 'policies', 'wording', 'wordings', 'brochure', 'brochures', 'prospectus', 'cis', 'customer', 'information',
                 'sheet', 'know', 'your', 'health', 'life', 'general', 'insurance', 'insurances', 'plan', 'plans', 'product', 'products',
                 'document', 'documents', 'download', 'pdf', 'terms', 'and', 'conditions', 'sales', 'literature', 'leaflet', 'the',
                 'of', 'company', 'limited', 'ltd', 'co', 'details', 'new', 'final', 'web', 'individual', 'group', 'retail'}
INSURER_FILLER = {'insurance', 'life', 'general', 'company', 'limited', 'ltd', 'co', 'the', 'of', 'and'}
FUNCTION_END = {'is', 'are', 'the', 'of', 'and', 'or', 'to', 'for', 'a', 'an', 'in', 'with', 'by', 'on', 'be', 'as', 'at', 'from', 'that'}


def bad_name(name, insurer=''):
    """True when a product-name candidate is not a usable product name."""
    n = re.sub(r'\s+', ' ', (name or '')).strip(' .,:;-|')
    if len(n) < 4 or JUNK_NAME.search(n) or LABEL_NAME.search(n):
        return True
    words = re.findall(r'[a-z0-9]+', n.lower())
    if not words or len(words) > 12:
        return True
    insurer_words = set(re.findall(r'[a-z0-9]+', (insurer or '').lower()))
    # Only doc words ("Policy Wording", "health"), or only the insurer's own name ("HDFC ERGO General Insurance").
    if set(words) <= GENERIC_WORDS or set(words) <= insurer_words | INSURER_FILLER:
        return True
    ends_badly = words[-1] in FUNCTION_END and not (words[-1] == 'on' and len(words) > 1 and words[-2] == 'add')
    if ends_badly or (len(words) > 6 and re.search(r'\b(is|are|shall|will|means|unless)\b', n, re.I)):
        return True
    return False


def first_good_name(cands, insurer):
    """First (name, source) whose name is not junk, else ('', '')."""
    for n, src in cands:
        n = n or ''
        if '_' in n or (len(n) > 12 and ' ' not in n):
            n = clean_filename(n)                                    # file-name-like titles and link texts
        n = re.sub(r'^\d{1,3}\s+(?=[A-Za-z])', '', n.strip())     # list numbering "11 Accident Shield"
        n = re.sub(r'(\s+(modified|view|download|pdf))+\s*$', '', n, flags=re.I)
        n = re.sub(r'\(?\s*UIN\s*[:\-]?\s*\)?', ' ', n, flags=re.I)
        n = re.sub(r'\d{3}[A-Z]\d{3}V\d{2}|[A-Z]{6,10}\d{5}V\d{6}', ' ', n, flags=re.I)
        n = re.sub(r'\s+', ' ', n).strip(' .,:;-|–()')
        if n and not bad_name(n, insurer):
            return n, src
    return '', ''


def link_wins(cand, flat, pdf_uin):
    """A link-page or URL UIN is kept only if the PDF's first pages contain it or show no clear UIN.
    An old-format IRDA reference in the PDF does not beat a modern UIN on the link page or URL."""
    return bool(cand) and (cand in flat or not pdf_uin or (bool(UIN_OLD.fullmatch(pdf_uin)) and not UIN_OLD.fullmatch(cand)))


def norm(x):
    return re.sub(r'[^a-z0-9]+', ' ', (x or '').lower()).strip()


# Doc-type words: a name made only of these ("policy wording", "brochures", "health") is shared by many products.
SIBLING_DOC_WORDS = {'policy', 'wording', 'wordings', 'brochure', 'brochures', 'prospectus', 'cis', 'health', 'life',
             'insurance', 'plan', 'form', 'forms', 'customer', 'information', 'sheet', 'document', 'documents',
             'sales', 'literature', 'terms', 'conditions', 'and', 'of', 'the', 'pdf', 'download', 'leaflet'}


def sibling_index(rows):
    """insurer -> normalised product name -> UIN, only for names that map to exactly one UIN within the
    insurer and are not made only of doc-type words."""
    names = collections.defaultdict(lambda: collections.defaultdict(set))
    for r in rows:
        if r['uin'] and r['product_name']:
            names[r['insurer_legal_name']][norm(r['product_name'])].add(r['uin'])
    out = collections.defaultdict(dict)
    for ins, d in names.items():
        for n, uins in d.items():
            if len(uins) == 1 and set(n.split()) - SIBLING_DOC_WORDS:
                out[ins][n] = next(iter(uins))
    return out


def fill_names(rows, url_names):
    """Rows still without a usable name: the most common usable name of the insurer's other documents with the same
    UIN (name_source 'sibling_uin'), else the cleaned URL file name, else blank."""
    by_uin = collections.defaultdict(collections.Counter)
    for r in rows:
        if r['uin'] and r['product_name'] and r['name_source'] not in ('url', 'sibling_uin'):
            by_uin[(r['insurer_legal_name'], r['uin'])][r['product_name']] += 1
    for r, url_name in zip(rows, url_names):
        if r['product_name']:
            continue
        names = by_uin.get((r['insurer_legal_name'], r['uin'])) if r['uin'] else None
        if names:
            r['product_name'], r['name_source'] = names.most_common(1)[0][0], 'sibling_uin'
        elif url_name and not bad_name(url_name, r['insurer_legal_name']):
            r['product_name'], r['name_source'] = url_name, 'url'
        if not r['category']:
            r['category'] = category(r['uin'], r['product_name'], r['insurer_legal_name'], r['doc_type'])
        missing = [k for k in ('uin', 'insurer_legal_name', 'product_name', 'category') if not r[k]]
        r['tag_status'] = 'complete' if not missing else 'missing:' + '|'.join(missing)


def main():
    global REGISTRY
    REGISTRY = load_registry()
    print(f'registry uins={len(REGISTRY)}', file=sys.stderr)
    rows = [json.loads(l) for l in open(os.path.join(REPO, 'manifest.jsonl')) if l.strip()]
    out = []
    url_names = []
    for i, m in enumerate(rows):
        path = os.path.join(REPO, 'docs', m['path'])
        url = m.get('source_url', '')
        insurer = m.get('insurer_legal_name', '')
        link_uin = (m.get('uin') or '').strip().upper()
        if link_uin and not (UIN_GENERAL_LOOSE.fullmatch(link_uin) or UIN_LIFE.fullmatch(link_uin) or UIN_OLD.fullmatch(link_uin)):
            link_uin = find_uin(link_uin)
        url_uin = find_uin(urllib.parse.unquote(url).upper())
        name = (m.get('product_name') or '').strip()
        name_src = 'link_page'
        if not name or GENERIC_NAMES.match(name) or LABEL_NAME.search(name) or len(name) > 100:
            name, name_src = '', ''
        text, title = pdf_text(path) if os.path.exists(path) else ('', '')
        rider_doc = bool(re.search(r'rider', url + ' ' + name, re.I))
        pdf_uin, ambiguous = pick_uin(text, rider_doc)
        flat = re.sub(r'\s+', '', text).upper()
        # A link-page or URL UIN is kept only if the PDF's own first pages agree or say nothing clear.
        # Link pages often show a card's UIN next to another product's PDF; the document itself wins.
        uin, uin_src = '', ''
        for cand, src in ((link_uin, 'link_page'), (url_uin, 'url')):
            if link_wins(cand, flat, pdf_uin):
                uin, uin_src = cand, src
                break
        if not uin and pdf_uin:
            uin, uin_src = pdf_uin, ('pdf_text_over_link' if (link_uin or url_uin) else 'pdf_text')
        if not uin and not ambiguous and os.path.exists(path):
            deep, _ = pdf_text(path, pages=60)
            uin, ambiguous = pick_uin(deep, rider_doc)
            uin_src = 'pdf_text_deep'
        # First usable name: link page, PDF text, PDF title. The URL name is held for the post-pass, after a sibling
        # document with the same UIN has had the chance to give a better one.
        title_ok = title and not GENERIC_NAMES.match(title) and len(title) < 100 and not re.search(r'microsoft|untitled|\.docx?$', title, re.I)
        name, name_src = first_good_name([(name, name_src), (name_from_text(text, uin) if text else '', 'pdf_text'),
                                          (title if title_ok else '', 'pdf_title')], insurer)
        url_names.append(name_from_url(url))
        if not uin:
            uin_src = 'ambiguous_pdf_text' if ambiguous else ''
        reg_name = REGISTRY.get(re.sub(r'\s+', '', uin).upper()) if uin else None
        if reg_name:
            name, name_src = reg_name, 'registry'
        dtype = doc_type_of(m.get('doc_type', ''), url, name)
        cat = category(uin, name, insurer, dtype)
        missing = [k for k, v in (('uin', uin), ('insurer_legal_name', insurer), ('product_name', name), ('category', cat)) if not v]
        out.append({
            'sha256': m['sha256'], 'pdf_path': 'docs/' + m['path'], 'source_url': url,
            'insurer_legal_name': insurer, 'uin': uin, 'product_name': name, 'category': cat,
            'doc_type': dtype, 'uin_source': uin_src, 'name_source': name_src,
            'tag_status': 'complete' if not missing else 'missing:' + '|'.join(missing),
            'verification': 'extracted_unverified',
        })
        if i % 200 == 0:
            print(f'{i}/{len(rows)}', file=sys.stderr)
    # Inherit a UIN from a sibling document of the same insurer with the same product name.
    fill_names(out, url_names)
    by_ins = sibling_index(out)
    for r in out:
        if r['uin'] or not r['product_name']:
            continue
        n = norm(r['product_name'])
        if len(n) < 6:
            continue
        hit = by_ins[r['insurer_legal_name']].get(n)  # exact normalised name only; substring matches spread wrong UINs
        if hit:
            r['uin'], r['uin_source'] = hit, 'sibling_doc_same_product'
            if REGISTRY.get(hit):
                r['product_name'], r['name_source'] = REGISTRY[hit], 'registry'
            if not r['category']:
                r['category'] = category(hit, r['product_name'], r['insurer_legal_name'], r['doc_type'])
        missing = [k for k in ('uin', 'insurer_legal_name', 'product_name', 'category') if not r[k]]
        r['tag_status'] = 'complete' if not missing else 'missing:' + '|'.join(missing)
    write_catalog(out)


def write_catalog(out):
    # One row per PDF: the same bytes reached through two links (5 cases) keep the first row, so loaders do not
    # flip a stored key between two names on every run.
    seen = set()
    out = [r for r in out if not (r['sha256'] in seen or seen.add(r['sha256']))]
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


def refresh_names():
    """--refresh-names: re-apply the name rules to the current catalog without re-reading PDFs. A name the rules now
    reject is cleared and refilled by fill_names (same-UIN sibling, then the cleaned URL name, else blank)."""
    out = [json.loads(l) for l in open(os.path.join(REPO, 'catalog.jsonl')) if l.strip()]
    cleared = 0
    for r in out:
        if r['product_name'] and r['name_source'] != 'registry' and bad_name(r['product_name'], r['insurer_legal_name']):
            r['product_name'], r['name_source'] = '', ''
            cleared += 1
    fill_names(out, [name_from_url(r['source_url']) for r in out])
    print(f'refresh-names cleared={cleared}', file=sys.stderr)
    write_catalog(out)


if __name__ == "__main__":
    refresh_names() if '--refresh-names' in sys.argv else main()
