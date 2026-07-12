# Submission Checklist

Please hand back a single zip (or a link to a Git repo) containing the following. The
items in **bold** are the ones we weigh most heavily.

## Code & outputs
- [ ] **`consolidate.py`** (and any supporting modules) — the tool itself.
- [ ] **`requirements.txt`** listing your dependencies.
- [ ] A short note on how to run it. We will run it in a fresh virtual environment, e.g.:
      ```bash
      python -m venv venv && source venv/bin/activate   # or venv\Scripts\activate on Windows
      pip install -r requirements.txt
      python consolidate.py
      ```
- [ ] **`clean.csv`** and **`errors.csv`** — the outputs your tool produced.

## Documentation
- [ ] **`README.md`** — a user guide (how to run) **plus** brief technical notes:
      - key design decisions and tradeoffs,
      - assumptions and any judgement calls you made on ambiguous rules,
      - how your solution would (or wouldn't) scale, and what you'd change first.

## AI usage  *(we genuinely want to see this — it is not a trap)*
- [ ] **AI transcript(s)** — export or paste the prompts/conversations you had with your
      AI tools while building this. Rough is fine; we want to see how you actually worked,
      not a polished script. If you used a CLI/agent tool, a session log or summary of the
      prompts is perfect.
- [ ] **`AI_REFLECTION.md`** (about one page) covering:
      - which AI tools you used and for what,
      - what you delegated to AI vs. decided/wrote yourself,
      - a place where the AI was **wrong or misleading**, and how you caught it,
      - if you took the AI route for the category step: how you'd make it reliable and
        affordable at ~50k rows/week.

## Optional
- [ ] Notes or a stub for the recurring-pipeline stretch (see the brief).
- [ ] Any tests you wrote (a few are a strong positive signal).

---

**A note on AI:** using AI heavily is fine and expected. But in the live round you will
**extend and debug this exact code with us**, so make sure you understand every part of
what you submit. The fastest way to do poorly is to hand in code you can't change.
