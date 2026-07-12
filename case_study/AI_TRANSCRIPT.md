# AI Usage Transcript Summary

This is a concise session summary. The original ChatGPT conversation can also
be exported and included with the submission.

## Detailed chat
https://chatgpt.com/share/6a53b546-80c8-83ec-abfa-67b62eafd1ad

## Requirements review

**User:** Before solutions, break down the objectives, requirements, do's, and
do-not-do items one by one.

**AI:** Inspected the brief, checklist, data dictionary, and SQLite tables. It
identified the seven rejection rules, required normalisation, deliverables,
reference values, and judgement calls such as region matching, invalid-region
routing, merchant-name matching, and deduplication.

## Category feasibility

**User:** Assess whether simple classification can handle the category free
text, including future multilingual values.

**AI:** Counted 195 rows and 43 distinct descriptions. It found that a simple
mapping could cover the sample but would not generalise reliably to unseen,
multilingual, misspelled, vague, or code-switched descriptions. It recommended
deterministic handling for known values and uncertainty-aware semantic handling
for novel values.

## Hardcoding correction

**User:** The solution cannot be hardcoded. Confirm whether the brief requires
an LLM and whether it prohibits hardcoded categories.

**AI:** Initially interpreted the constraint too broadly, then corrected the
reading after the user challenged it. The brief does not require an LLM and
explicitly permits rules, keywords, and embeddings. It does require canonical
categories, region/PIC mappings, and existing merchants to come from SQLite
rather than Python constants.

## Incremental LLM proposal

**User:** Proposed batching unique free-text descriptions into JSON, caching
classifications, and reusing exact or similar matches so the system becomes
less dependent on the LLM.

**AI:** Confirmed the direction. It refined the design to normalise and
deduplicate text before calls, reuse exact matches, treat similarity cautiously,
batch unresolved items, validate compact JSON, version cache records against
the taxonomy, and use a separate SQLite cache rather than mutating
`reference.db`.

## Cost and batching

**User:** Asked whether batching was included and whether JSON was more
cost-effective.

**AI:** Confirmed configurable batching. It clarified that JSON improves
structure, while the material savings come from unique-value classification,
cache reuse, batching, and compact category IDs. SQLite and JSON caches provide
the same token savings, but SQLite is safer for repeated execution.

## Provider selection

**User:** Proposed GitHub Models using Azure AI Inference and
`openai/gpt-5`.

**AI:** Verified the current GitHub Models and Azure AI Inference documentation.
It confirmed the endpoint and model availability, recommended environment-only
credentials with `models:read`, strict response validation, retry handling,
provider isolation, usage tracking, and evaluation of smaller models for cost.

## Implementation

**User:** Requested the code, with submissions under `data/`.

**AI:** Implemented the SQL-driven pipeline, batched classifier, persistent
taxonomy-versioned cache, validation, normalisation, deduplication, CSV outputs,
tests, README, transcript summary, and this reflection. It ran the pipeline on
all supplied rows, audited duplicate groups and rejection reasons, and ran the
automated test suite.
