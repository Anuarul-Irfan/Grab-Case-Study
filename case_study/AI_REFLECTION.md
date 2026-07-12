# AI Reflection

I used ChatGPT Work/Codex as a design and implementation partner and GitHub
Models as the proposed runtime category-classification service. ChatGPT helped
me inspect the brief, data dictionary, SQLite reference data, and the three
submission files. I also used it to challenge the category strategy, implement
the Python pipeline, produce tests, and review operational risks. The runtime
code uses the Azure AI Inference SDK with GitHub Models, although the supplied
sample run was resolved from a reviewed cache and therefore did not require a
live token.

I delegated mechanical work and adversarial review to AI: enumerating distinct
category descriptions, drafting validation code, constructing test cases, and
checking whether the design satisfied each stated rule. I retained the main
decisions: use an LLM rather than a fixed vocabulary for multilingual future
inputs, classify unique values in batches, persist reviewed results, keep the
reference database authoritative, and reject uncertainty rather than force a
category. I chose the GitHub Models endpoint and GPT-5 integration, while
keeping the endpoint, model, and batch size configurable.

One useful case where the AI was misleading concerned hardcoding. It initially
said that an exact alias dictionary would be prohibited. After I reread the
brief and challenged that claim, we established the more accurate distinction:
the canonical reference lists must not be hardcoded, but the brief explicitly
permits a rules/keyword approach. This changed how I documented the decision.
The LLM design is a deliberate scalability choice, not something the exercise
requires.

I also did not accept generated code without verification. I checked the
database tables with SQL, counted all 195 inputs and 43 distinct descriptions,
ran the pipeline end to end, inspected the rejection distribution, audited
every duplicate group, and ran automated tests. Model output is treated as
untrusted input: Python verifies JSON structure, completeness, unique item IDs,
status consistency, and category IDs against the current SQL results before a
classification can be cached or written to output.

At roughly 50,000 rows per week, I would keep the LLM reliable and affordable
by sending only free-text descriptions, normalising and deduplicating them,
reusing exact approved cache matches, and batching only unseen unique values.
For example, 50,000 rows might reduce to a few thousand unique descriptions and
only a few hundred cache misses. Compact numeric IDs reduce response tokens.
Batch-level retry and taxonomy, prompt, and model versioning make failures and
changes traceable.

The largest long-term risk is not token cost but persistent error: a bad model
decision can be reused indefinitely. Production improvements would therefore
include a human-review queue, correction history, quality metrics by language,
and periodic evaluation against a reviewed multilingual dataset. Once enough
reviewed examples accumulate, I would train a smaller local classifier and use
the LLM only for new or ambiguous cases. That makes the cache an incremental
source of labelled data rather than merely permanent memory.
