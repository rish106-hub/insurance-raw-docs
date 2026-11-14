#!/usr/bin/env python3
"""Add a `purpose` column (claims | service | grievance | other | blank) to links/insurer-contacts.csv.

Run after tools/insurer-contacts.py. Deterministic rules on the e-mail local part and on the text just
before a phone number in its example line. Blank when unsure. Rows that are not helplines at all are
dropped: a number labelled Fax, and e-mails that are extraction artefacts (a word glued to the address).

usage: contact-purpose.py <links/insurer-contacts.csv>   (rewrites in place)
"""
import csv, re, sys

GRIEV = re.compile(r'griev|^gro$|complaint|^head\.|^manager\.')
CLAIMS = re.compile(r'^claims?(\.|$)|^claims\.(support|seniorcitizen|unit)$')
OTHER = re.compile(r'nri|^riservice$|group|fund')
SERVICE = re.compile(r'service|customer|^care$|support|wecare|^info$|^onlinequery$|helpdesk')
ARTEFACT = {'atonlinequery'}  # "at onlinequery@..." glued by text extraction


def email_purpose(local):
    local = local.lower()
    if local in ARTEFACT:
        return None
    for rx, p in ((GRIEV, 'grievance'), (OTHER, 'other'), (CLAIMS, 'claims'), (SERVICE, 'service')):
        if rx.search(local):
            return p
    return ''


def phone_purpose(value, line):
    digits = value.replace('-', '')
    # find the number in the line allowing spaces/dashes between digits
    rx = re.compile(r'[\s-]?'.join(digits))
    m = rx.search(line)
    if not m:
        return ''
    # window: text before the number, back to the previous number or 40 chars
    before = line[max(0, m.start() - 40):m.start()]
    before = re.split(r'\d{4,}[\s\d-]*', before)[-1].lower()
    if 'fax' in before:
        return None
    if 'sales' in before:
        return 'other'
    if 'claim' in before:
        return 'claims'
    if 'service' in before or 'help' in before or 'toll' in before or 'call' in before or 'contact' in before:
        return 'service'
    # nothing next to the number: fall back to the line's lead-in, service only, never on a mixed line
    lead = re.split(r'\d{4}[\s-]?\d{3}', line)[0].lower()
    if not re.search(r'claim|fax|sales|griev', line.lower()) and re.search(r'help|toll|call|contact|service', lead):
        return 'service'
    return ''


def main(fp):
    rows = list(csv.DictReader(open(fp, newline='', encoding='utf-8')))
    if not rows:
        sys.exit('empty')
    fields = [f for f in rows[0].keys() if f != 'purpose']
    fields.insert(fields.index('value') + 1, 'purpose')
    out, dropped = [], []
    for r in rows:
        if r['kind'] == 'email':
            p = email_purpose(r['value'].split('@')[0])
        else:
            p = phone_purpose(r['value'], r.get('example_line', ''))
        if p is None:
            dropped.append(r['value'])
            continue
        r['purpose'] = p
        out.append(r)
    with open(fp, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows({k: r.get(k, '') for k in fields} for r in out)
    counts = {}
    for r in out:
        counts[r['purpose'] or 'blank'] = counts.get(r['purpose'] or 'blank', 0) + 1
    print({'rows': len(out), 'dropped': dropped, 'purpose': counts})


if __name__ == '__main__':
    main(sys.argv[1])
