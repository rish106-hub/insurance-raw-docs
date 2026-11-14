# Golden cases from real insurer documents

`number-formats.jsonl`: number shapes seen in a random sample of 220 collected insurer PDFs (first 4 pages),
with hand-derived expected values, for the shared number normaliser in CoverSaath `chat-answer-guard`
(architecture-v1, B12 / R7). Money is in paise (`expected` = minor units; 1 lakh = 1,00,000 rupees;
1 crore = 1,00,00,000 rupees). Durations keep their unit (a month is not a fixed number of days).
`none` rows are noise the normaliser must reject. Strings are public document text; no personal data.
