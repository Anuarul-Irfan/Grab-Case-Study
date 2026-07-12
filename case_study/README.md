# Merchant Submission Consolidation

`consolidate.py` validates, normalises, classifies, and deduplicates merchant
submissions from all partner CSV files in `data/`. It writes accepted merchants
to `clean.csv` and rejected submissions to `errors.csv`.

## Quick start

Python 3.10 or later is recommended.

```bash
python -m venv venv
source venv/bin/activate                # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

The project starts without a classification cache. Set a GitHub personal access
token with `models:read` permission before the first run:

```bash
cat > .env <<'EOF'
GITHUB_TOKEN=Your Github Token
EOF
python consolidate.py
```

On Windows, create a file named `.env` beside `consolidate.py` containing:

```env
GITHUB_TOKEN=Your Github Token
```

Then run:

```powershell
python consolidate.py
```

`python-dotenv` loads this file automatically. Never commit or share the token.
`.env` is excluded through `.gitignore`.

On the first run, the program creates `classification_cache.db` and sends the
43 unique descriptions in the supplied data to GitHub Models. With the default
batch size of 10, this is five model requests. Smaller batches prevent the model
from omitting items in a large structured response. Later runs reuse exact
cached descriptions and call the model only for new text.

Default paths:

```text
data/submissions_partner*.csv
reference.db
classification_cache.db
clean.csv
errors.csv
```

All can be changed through command-line options:

```bash
python consolidate.py --help
python consolidate.py \
  --input-glob "data/submissions_partner*.csv" \
  --reference-db reference.db \
  --cache-db classification_cache.db \
  --batch-size 10 \
  --model openai/gpt-4.1-mini
```

## Design overview

The program loads categories, region/PIC mappings, and existing merchants from
`reference.db` using SQL. The canonical lists are not duplicated in Python.

Processing order:

1. Read every partner CSV and verify its schema.
2. Load reference records in three SQL queries.
3. Normalise and deduplicate nonblank free-text category descriptions.
4. Reuse exact normalised matches from `classification_cache.db`.
5. Send only unique cache misses to GitHub Models in configurable batches.
6. Validate every returned status and category ID against `reference.db`.
7. Apply every business-rule validation to each submission.
8. Deduplicate valid merchants across all partner files.
9. Write deterministic clean and error outputs.

The LLM receives only free-text category descriptions and the categories loaded
from SQLite. Merchant names and contact information are not sent.

## Category classification

The default provider configuration is:

```text
Endpoint: https://models.github.ai/inference
Model:    openai/gpt-4.1-mini
Batch:    10 unique unresolved descriptions
```

The model receives a generic classification instruction, dynamically loaded
category IDs/names, and a batch of descriptions. It must return one supplied
category ID or `unmappable` in compact JSON. The response is rejected unless:

- it is valid JSON;
- every requested item appears exactly once;
- no unknown item appears;
- every mapped category ID exists in the current database;
- mapped and unmappable statuses have consistent category values.

The program retries transient rate-limit and server failures with bounded
backoff. It fails the run instead of guessing when unresolved descriptions
cannot be classified safely.

### Classification cache

The cache uses a separate SQLite database and never modifies `reference.db`.
Cache keys use Unicode normalisation, case folding, trimming, and whitespace
collapse. Only exact normalised matches are automatically reused. Approximate
matches are deliberately not reused because similar descriptions can refer to
different businesses.

Every entry stores its source, model, prompt version, review status, timestamp,
and a hash of the current category taxonomy. A category change therefore stops
old entries from being silently reused.

No cache is distributed with the project. It is created locally on the first
successful run and grows only from validated model responses. The cache is a
runtime artifact rather than a hardcoded vocabulary or submitted seed dataset.

## Business-rule decisions

### Required fields

Whitespace-only values are blank. Missing fields are reported individually.
`submission_id` is additionally required for traceability, and duplicate IDs
are treated as an input-integrity failure rather than a merchant rejection.

### Regions

Regions are matched after Unicode normalisation, trimming, whitespace collapse,
and case folding. Accepted output uses the canonical database spelling. An
invalid region has no resolvable PIC, so its error-row PIC email is blank.

### Email

The test checks a plausible `local@domain.tld` shape without attempting mailbox
verification or full RFC conformance. Accepted emails are lowercased.

### Phone

All non-digits are removed. A leading `+60` or `60` becomes a leading `0`.
Numbers with fewer than nine digits after normalisation are rejected. No
unstated maximum length is imposed.

### Dates

Only `YYYY-MM-DD` and `D/M/YYYY` are parsed. Output is ISO `YYYY-MM-DD`. Calendar
validation uses the fixed reference date `2026-06-01`, never the system date.

### Existing merchants

IDs use exact comparison against SQL reference data. Names use conservative
case-insensitive, whitespace-normalised equality. Fuzzy name matching is not
used because false positives could reject a genuinely new business. A nonblank
unknown ID is not rejected unless the name also matches.

### Deduplication

Valid rows are grouped by normalised merchant name plus canonical region. This
handles contact-detail differences while reducing false merges between regions.
The lexicographically smallest `submission_id` wins, making the result independent
of input file ordering. `duplicates_collapsed` is the number of additional valid
rows removed from the group. Valid duplicates do not go to `errors.csv`.

One supplied duplicate group has conflicting category descriptions. The same
deterministic winner rule applies; this is documented rather than silently using
filesystem order.

### Multiple errors

All safely detectable row-level problems are reported in one
`rejection_reasons` cell separated by `; `. An invalid row is still category
classified when its category text is present, allowing the output to report
multiple applicable issues.

## Current run

The included outputs were produced while validating the implementation against
the three supplied partner files. A clean first run will classify all 43 unique
descriptions through the configured GitHub Models endpoint before recreating
the outputs:

```text
Input rows:                     195
Valid rows before deduplication: 136
Clean rows:                     116
Rejected rows:                   59
Valid duplicates collapsed:      20
Unique category descriptions:     43
First-run LLM descriptions:        43
First-run LLM batches:               5
```

Each live batch prints its input, output, and total token count. The completion
summary also reports aggregate `prompt_tokens`, `completion_tokens`, and
`total_tokens`. A fully cached run reports zero new tokens because it does not
call the model.

GitHub-side metered usage is available under GitHub **Settings → Billing and
Licensing → Metered usage**, where it can be filtered to GitHub Models. The
billing view may update later than the local program output.

## Tests

Tests use Python's standard `unittest` library and mock classification, so they
do not need a GitHub token or network connection.

```bash
python -m unittest discover -s tests -v
```

Coverage includes phone/date normalisation, taxonomy-scoped cache behaviour,
strict model-response validation, multi-error reporting, existing-merchant
rejection, and deterministic deduplication.

## Scaling and tradeoffs

The program streams each CSV through the standard library but retains rows in
memory so it can validate and deduplicate the complete weekly set. Tens of
thousands of rows are reasonable. Reference tables are loaded once, category
text is deduplicated before classification, and only cache misses consume model
requests.

The local SQLite cache is appropriate for a single process. For continuous or
concurrent production runs, the first changes would be:

- move the cache and run metadata to a central transactional database;
- stage inputs and publish outputs atomically;
- assign idempotent run IDs and record input checksums;
- use a queue for classification and human review;
- add monitoring for model usage, cache hit rate, corrections, and drift;
- train a smaller multilingual model from reviewed classifications, retaining
  the LLM as a fallback for novel descriptions.

GitHub Models' free inference endpoint is suitable for prototyping and is rate
limited. Continuous production usage would require an appropriate paid tier or
provider configuration. The model and endpoint are command-line configurable,
and provider-specific code is isolated in `classification.py`.

## Troubleshooting

### `Unavailable model: gpt-5`

The account does not have access to that model. The project defaults to the
working catalog identifier `openai/gpt-4.1-mini`.

### `The model omitted one or more requested items`

The model returned an incomplete batch. The default batch size is 10, which was
successfully tested on the supplied 43 descriptions. If it occurs again, retry
with a smaller batch:

```powershell
python consolidate.py --batch-size 5
```

Only complete, validated batches are cached. Successful earlier batches remain
available if a later batch fails.
