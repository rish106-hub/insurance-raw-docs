# Handoff: raw insurer PDF collection (Squad B, FSS real-data lane)

Written 2026-11-14 for the next agent. Read this, then `README.md`.

## Goal

Collect every public health, life, term life and health add-on document (policy wording, CIS, prospectus,
brochure, forms) from Indian insurers. Store the raw PDFs unparsed. Tag every PDF with the five
must-haves the owner set: **UIN, insurer name, policy name, category, PDF (path + source URL)**.

Briefs: `CoverSaath/docs/exec-plans/active/squad-b-brief.md`, `two-squads-2026-11-14.md`.

## State now

- 4,322 unique PDFs (3.9 GB), 21 insurers, all in this private repo (`rish106-hub/insurance-raw-docs`, `main`).
- `catalog.csv` / `catalog.jsonl`: one row per PDF with the five tags, `uin_source`, `name_source`,
  `tag_status` (`complete` or `missing:<fields>`), `verification=extracted_unverified`.
- `untagged.csv`: rows not complete. Before the latest tagger fix: 3,299 / 4,322 complete; 1,022 missing UIN,
  50 missing category. A retag with the improved tagger (decrypt owner-locked PDFs, 60-page UIN scan,
  `UIN:` label pattern) was run on 2026-11-14; check the latest commit for the new counts.
- insurance-data-api PRs #1 to #6 are all merged.

Per-insurer complete (before retag): Navi, Bajaj, Future Generali, ManipalCigna, SBI General, IFFCO, Niva 100%;
HDFC Life 979/990; HDFC ERGO 220/229; Royal Sundaram 186/189; SBI Life 164/171; Star 301/322;
Canara HSBC 340/474; Tata AIA 658/1040; SUD 84/147; Kotak 44/66; ICICI Lombard 31/50; Axis Max 86/325;
ICICI Pru 2/52; Care 1/61; ABHI 18/21.

## Decisions from the owner

- **Storage: Cloudflare R2 (PDF bytes) + Supabase free Postgres (rows)**. BUILT by Squad A in
  `insurance-data-api` branch `sqb/supabase-store`: migration 022 (`documents` keyed by sha256, FK to
  `insurers` and to `insurance_products` via UIN; `document_artifacts` for AI extraction XML/CSV/JSON;
  RLS on every table) and `npm run docs:load -- --catalog catalog.csv --docs-root docs` (re-hashes each
  PDF, uploads under readable key `<insurer>/<UIN|unassigned>/<product>__<doc_type>__<sha8>.pdf`,
  idempotent; re-run after every re-tag to refresh tags). Do not build another uploader. Waiting on the
  owner's R2 bucket/token and Supabase login (never read `.env*`).
- **Paused** (do not work on until the owner says): Oriental (site renders blank), Raheja QBE (site down), IRDAI.
- robots.txt waived. Never solve a CAPTCHA (the owner does). No logins, no personal data.
- Download everything, parse nothing. Tags are `extracted_unverified`.
- Deliberately skipped: about 150 Axis Max vernacular service forms, 21 Canara group admin forms,
  62 SBI Life/Kotak links that answered with a challenge (`held.csv`). 7 ICICI Lombard files dropped by the browser.

## Next work, in order

1. Raise tag completeness. Work `untagged.csv` by insurer: Care, ICICI Pru, Axis Max, Tata AIA, SUD, Canara.
   Many untagged rows are claim/service/KYC forms with no UIN: mark them `doc_type` form and leave UIN blank
   (never guess). For product docs, look up the UIN on the insurer's product page or the IRDAI product list
   once IRDAI is unpaused.
2. R2 upload + relational catalog (after the owner gives a bucket).
3. Lane log in `CoverSaath/docs/exec-plans/active/` with the counts.

## Tools (this repo)

| File | Use |
| --- | --- |
| `tag-catalog.py <repo-dir>` | Rebuilds catalog.csv/jsonl and untagged.csv. Run plain `python3` (not `-I`; pypdf and cryptography are in user site-packages) from a directory other than the repo. Takes about 30 minutes for all PDFs. |
| `ingest-browser.mjs <dl-dir> <tag> <store> <insurer> [links.csv]` | Moves browser-saved `fss-<tag>-NNNN.pdf` + `fss-map-<tag>.csv` into the store and manifest. |
| `ingest-bundle.mjs <bundle.jsonl> <store> <insurer>` | Ingests one `{url,page,status,b64}` jsonl saved by the browser (avoids Chrome's multiple-downloads block). |
| `sync.sh <store-dir>` | Copies the local store into this repo. |
| `links/*.csv` | Harvested link lists (`url,insurer_legal_name,uin,product_name,doc_type,source_url`). |

Local store (source of truth on the collecting Mac): `insurance-data-api.worktrees/.fss-data/raw/docs/`.
Shell downloader: `insurance-data-api/tools/raw-download.mjs` (merged in PR #6).

## Gotchas learned

- Star site times out from the shell; use the CDN URLs from the page. SUD PDFs live on
  `dxwkpt4djlxwl.cloudfront.net` (the www URL returns HTML).
- Navi PDF links sit in React props, not anchors. icicilife.com uses SVG anchors (`getAttribute('href')`).
- Chrome extension JS output truncates near 1,000 chars: have the page download a CSV instead.
- Chrome blocks repeated downloads per site: save one bundle file, or the owner sets the site's
  "Automatic downloads" to Allow.
- ICICI Pru PDFs are owner-password locked; pypdf opens them with `decrypt('')` (needs `cryptography`).
- UINs: general/health `[A-Z]{3,6}..\d{5}V\d{6}` (HLIP individual, HLGP group, HLIA add-on, PAIP accident);
  life `\d{3}[NLGB]\d{3}V\d{2}` (N non-linked, L linked, G group, B rider).
