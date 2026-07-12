# Take-Home Exercise — Operations Solution Specialist

Welcome, and thanks for your interest in the **Business Intelligence & Operations
Solution (BIOS)** team. This exercise mirrors the actual work of the role: turning a
messy, manual operational workflow into a clean, reliable, scalable automation.

- **Time budget:** ~3–5 hours. Please do not spend more — we would rather see a
  well-scoped, well-reasoned solution than an exhaustive one.
- **Deadline:** within **5 days** of receiving this brief.
- **Language:** Python.
- **AI tools:** **You are encouraged to use AI coding tools** (Claude Code, Cursor,
  Copilot, ChatGPT, etc.). Using them well is part of the role. See
  [The AI component](#the-ai-component) and the submission checklist — we ask you to
  show us *how* you used them.

You will demo and extend this same solution live in the next round, so build something
**you understand and can change on the spot**.

---

## The scenario

Every week, regional Business Development partners send our Operations team spreadsheets
of new merchants to onboard. The data is **inconsistent and partly invalid**: mixed
casing, duplicate submissions, malformed contact details, free-text business categories,
merchants that were already onboarded, and the occasional impossible date.

Today an ops analyst cleans this by hand. Your job is to **replace that manual review
with an automation.**

You have three input files (one per partner) and a small reference database.

## Your task

Build a Python tool — name it `consolidate.py` — that processes the three partner files
and produces two outputs:

1. **`clean.csv`** — the validated, normalised, de-duplicated merchants that are ready to
   onboard. One row per real merchant.
2. **`errors.csv`** — every rejected submission, each with a **clear, human-readable
   reason** so we can send it back to the right partner to fix.

Your tool must:

1. **Read the reference data from `reference.db` (SQLite) using SQL.** It contains the
   canonical business categories, the region → person-in-charge (PIC) email mapping, and
   the list of already-onboarded merchants. Do not hardcode these lists in Python.
2. **Validate** each submission against the business rules in
   [`DATA_DICTIONARY.md`](./DATA_DICTIONARY.md).
3. **Normalise** the valid rows (consistent casing/whitespace, phone format, dates).
4. **Classify** the free-text `business_category_freetext` into one of the canonical
   categories — see [The AI component](#the-ai-component).
5. **De-duplicate** — the same merchant may be submitted more than once, sometimes with
   slightly different formatting. Decide a sensible rule and apply it.
6. **Route errors** — each rejected row should carry the PIC email for its region so a
   human knows who to contact.
7. **Write both output files** efficiently (you are processing all partners in one run).

Read **[`DATA_DICTIONARY.md`](./DATA_DICTIONARY.md)** before you start — it defines every
column and every business rule precisely.

## The AI component

One column, `business_category_freetext`, is messy free text written by partners — e.g.
`"nasi lemak stall"`, `"mini grocer"`, `"phone repair"`. You must map each one to exactly
one **canonical category** from the `categories` table in `reference.db`. If a value
genuinely doesn't fit any category, it should be rejected (see the rules).

**How you solve this is up to you** — an LLM, a rules/keyword approach, embeddings,
anything. We mainly care that the step is **repeatable, testable, and would scale** to
tens of thousands of rows per week without becoming slow, expensive, or flaky. If you use
an LLM, think about how you would keep it reliable and affordable at that volume.

This part is deliberately representative of real BIOS work, so treat it as a small piece
of engineering, not a one-off prompt.

## What to hand back

See **[`SUBMISSION_CHECKLIST.md`](./SUBMISSION_CHECKLIST.md)** for the full list. In short:
your code, a `requirements.txt`, your `clean.csv` and `errors.csv`, a short README, your
**AI usage transcript(s)**, and a one-page **`AI_REFLECTION.md`**.

## Optional stretch (not required)

If — and only if — you have time left, add a short note (or stub) describing how you would
turn this into a **recurring pipeline**: it runs daily, several ops people may trigger it,
inputs arrive continuously, and a run might crash halfway. What would you change? We will
discuss this live regardless, so a few bullet points are plenty.

## How we evaluate

We assess: correctness, code quality (robust / scalable / maintainable), your SQL, how
well you used AI, your documentation, and — in the live round — how you reason about
scaling and how easily you can extend your own code. We care more about clear thinking and
solid engineering judgement than about catching every single edge case.

Good luck — we are genuinely looking forward to seeing how you work.
