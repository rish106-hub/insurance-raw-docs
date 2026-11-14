# insurance-raw-docs

Raw public insurer documents (policy wordings, CIS, prospectus, brochures, proposal forms) collected for the
FSS insurance-data-api prototype (`rish106-hub/insurance-data-api`). **Unparsed.** Parsing is a separate step.

| Path | What |
| --- | --- |
| `docs/<host>/<sha256>.<ext>` | Raw bytes, named by content hash (deduplicated) |
| `manifest.jsonl` | One line per stored file: `sha256`, `path` (relative to `docs/`), `source_url`, `insurer_legal_name`, `uin`, `product_name`, `doc_type`, `fetched_at`, `collection_method`, `robots_consulted`, `parsed` |
| `attempts.jsonl` | Every download attempt and its outcome |
| `held.csv` | URLs held because the site answered with a challenge (CAPTCHA, bot wall, 403) |
| `links/` | Link lists harvested from insurer download pages (input to the downloader) |

Collected with `tools/raw-download.mjs` from insurance-data-api. Owner waived robots.txt for this prototype
collection (`robots_consulted: false`). Challenges are never solved by the tool.

Rights: store and transform allowed for the prototype; serving or redistributing the documents is not
(see `docs/source-rights-register.md` in insurance-data-api, FOR LEGAL REVIEW). Keep this repo private.

Storage: `insurance-data-api` `npm run docs:load` (branch `sqb/supabase-store`) loads `catalog.csv` into the
relational `documents` table and uploads `docs/` to private Cloudflare R2. See `HANDOFF.md`.
