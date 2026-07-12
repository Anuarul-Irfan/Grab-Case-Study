# Data Dictionary & Business Rules

This document defines the input data, the reference database, and every business rule your
tool must enforce. When a rule below is unambiguous, follow it exactly. Where you have to
make a judgement call, **document your choice** in your README — we value clear reasoning.

> **Reference date:** Treat **`2026-06-01`** as "today" for all date checks. (Using a
> fixed date keeps results reproducible — please don't use the real current date.)

---

## Input files — `data/submissions_partnerA.csv`, `…partnerB.csv`, `…partnerC.csv`

One row per submitted merchant. All three files share the same columns:

| Column | Meaning | Notes |
|---|---|---|
| `submission_id` | Unique ID for the submission row | Prefixed by partner (`A001`, `B012`, …). Unique within the whole dataset. |
| `merchant_name` | Business name | May have inconsistent casing and stray whitespace. |
| `business_category_freetext` | Partner's free-text description of the business | Must be mapped to a canonical category. May be unmappable. |
| `region` | Operating region | Must be one of the canonical regions (see `region_pic`). |
| `contact_phone` | Contact phone number | Mixed formats: with/without dashes, occasional `+60` international prefix. |
| `contact_email` | Contact email | May be malformed. |
| `registration_date` | Business registration date | Two formats appear: `YYYY-MM-DD` and `D/M/YYYY`. |
| `existing_merchant_id` | Set if the partner flagged this as an existing merchant | Usually blank. A blank value does **not** guarantee the merchant is new (see Rule 7). |

---

## Reference database — `reference.db` (SQLite)

Query this with SQL. Three tables:

### `categories`
| Column | Type | Notes |
|---|---|---|
| `category_id` | INTEGER PK | |
| `canonical_name` | TEXT | The only valid category labels. e.g. `Food & Beverage`. |

### `region_pic`
| Column | Type | Notes |
|---|---|---|
| `region` | TEXT PK | The canonical set of valid regions. |
| `pic_name` | TEXT | Person in charge for that region. |
| `pic_email` | TEXT | Email to route submissions/errors to. |

### `existing_merchants`
| Column | Type | Notes |
|---|---|---|
| `merchant_id` | TEXT PK | e.g. `M0007`. |
| `merchant_name` | TEXT | Name of an already-onboarded merchant. |

You can inspect it quickly:

```python
import sqlite3
con = sqlite3.connect("reference.db")
for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'"):
    print(row)
print(con.execute("SELECT canonical_name FROM categories").fetchall())
```

---

## Business rules

A submission is **rejected** (goes to `errors.csv`) if it violates **any** rule below. A
submission that passes all rules is **normalised** and kept (and then de-duplicated).

| # | Rule | Reject when… |
|---|---|---|
| 1 | **Required fields** | `merchant_name`, `region`, `contact_phone`, `contact_email`, `registration_date`, or `business_category_freetext` is blank. |
| 2 | **Valid region** | `region` is not one of the regions in `region_pic`. |
| 3 | **Valid email** | `contact_email` is not a plausible email (`local@domain.tld`). |
| 4 | **Valid phone** | After normalising, the phone has fewer than 9 digits. |
| 5 | **Mappable category** | `business_category_freetext` cannot be mapped to any `categories.canonical_name`. |
| 6 | **Sane date** | `registration_date` cannot be parsed, **or** it is after the reference date (`2026-06-01`). |
| 7 | **Not already onboarded** | The merchant already exists in `existing_merchants` — matched **either** by `existing_merchant_id` **or** by name. |

**Normalisation expected for kept rows:**

- `merchant_name`: trim, collapse internal whitespace, consistent casing.
- `contact_email`: trimmed, lower-cased.
- `contact_phone`: digits only; convert a leading `+60`/`60` to a `0` prefix.
- `registration_date`: output a single consistent format (ISO `YYYY-MM-DD` recommended).
- `business_category_freetext` → its canonical category.

**De-duplication:** the same real merchant can appear more than once (across or within
files), sometimes differing only by casing/whitespace or contact details. Collapse these
to one row. You decide the matching key and which record "wins" — **state your rule**.

---

## Suggested output columns (you may adjust — explain if you do)

**`clean.csv`**: `merchant_name`, `canonical_category`, `region`, `contact_phone`,
`contact_email`, `registration_date`, `region_pic_email`, `source_submission_id`,
`duplicates_collapsed`.

**`errors.csv`**: `submission_id`, `source_file`, `merchant_name`, `region`,
`region_pic_email`, `rejection_reasons` (human-readable; one row may break several rules).
