#!/usr/bin/env python3
"""Consolidate partner merchant submissions into clean.csv and errors.csv."""

from __future__ import annotations

import argparse
import csv
import glob
import re
import sqlite3
import sys
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, Sequence
from dotenv import load_dotenv

load_dotenv()

from classification import (
    DEFAULT_ENDPOINT,
    DEFAULT_MODEL,
    Category,
    ClassificationError,
    classify_descriptions,
    normalize_category_text,
)


REFERENCE_DATE = date(2026, 6, 1)

INPUT_COLUMNS = [
    "submission_id",
    "merchant_name",
    "business_category_freetext",
    "region",
    "contact_phone",
    "contact_email",
    "registration_date",
    "existing_merchant_id",
]

REQUIRED_FIELDS = [
    "merchant_name",
    "region",
    "contact_phone",
    "contact_email",
    "registration_date",
    "business_category_freetext",
]

CLEAN_COLUMNS = [
    "merchant_name",
    "canonical_category",
    "region",
    "contact_phone",
    "contact_email",
    "registration_date",
    "region_pic_email",
    "source_submission_id",
    "duplicates_collapsed",
]

ERROR_COLUMNS = [
    "submission_id",
    "source_file",
    "merchant_name",
    "region",
    "region_pic_email",
    "rejection_reasons",
]

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s.]{2,}$")


class InputError(RuntimeError):
    """Raised for file, schema, or reference database problems."""


@dataclass(frozen=True)
class RegionPIC:
    region: str
    pic_email: str


@dataclass(frozen=True)
class ReferenceData:
    categories: tuple[Category, ...]
    regions_by_key: dict[str, RegionPIC]
    existing_ids: frozenset[str]
    existing_names: frozenset[str]


@dataclass
class Submission:
    source_file: str
    values: dict[str, str]


@dataclass
class ValidMerchant:
    submission_id: str
    merchant_name: str
    merchant_identity: str
    canonical_category: str
    region: str
    contact_phone: str
    contact_email: str
    registration_date: str
    region_pic_email: str


def compact_whitespace(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).strip().split())


def identity_key(value: str) -> str:
    return compact_whitespace(value).casefold()


def normalise_merchant_name(value: str) -> str:
    return compact_whitespace(value).title()


def normalise_phone(value: str) -> str:
    digits = re.sub(r"\D", "", value)
    if digits.startswith("60"):
        digits = "0" + digits[2:]
    return digits


def parse_registration_date(value: str) -> date | None:
    stripped = value.strip()
    for date_format in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(stripped, date_format).date()
        except ValueError:
            continue
    return None


def load_reference_data(path: str | Path) -> ReferenceData:
    db_path = Path(path)
    if not db_path.is_file():
        raise InputError(f"Reference database not found: {db_path}")

    try:
        connection = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        category_rows = connection.execute(
            "SELECT category_id, canonical_name FROM categories ORDER BY category_id"
        ).fetchall()
        region_rows = connection.execute(
            "SELECT region, pic_email FROM region_pic ORDER BY region"
        ).fetchall()
        merchant_rows = connection.execute(
            "SELECT merchant_id, merchant_name FROM existing_merchants"
        ).fetchall()
    except sqlite3.Error as exc:
        raise InputError(f"Could not read reference database: {exc}") from exc
    finally:
        if "connection" in locals():
            connection.close()

    if not category_rows:
        raise InputError("The categories reference table is empty.")
    if not region_rows:
        raise InputError("The region_pic reference table is empty.")

    categories = tuple(
        Category(int(row["category_id"]), str(row["canonical_name"]))
        for row in category_rows
    )
    regions = {
        identity_key(row["region"]): RegionPIC(
            region=str(row["region"]), pic_email=str(row["pic_email"])
        )
        for row in region_rows
    }
    return ReferenceData(
        categories=categories,
        regions_by_key=regions,
        existing_ids=frozenset(str(row["merchant_id"]).strip() for row in merchant_rows),
        existing_names=frozenset(
            identity_key(str(row["merchant_name"])) for row in merchant_rows
        ),
    )


def read_submissions(paths: Sequence[str | Path]) -> list[Submission]:
    submissions: list[Submission] = []
    seen_ids: set[str] = set()
    for path_value in paths:
        path = Path(path_value)
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                actual_columns = reader.fieldnames or []
                missing_columns = [col for col in INPUT_COLUMNS if col not in actual_columns]
                if missing_columns:
                    raise InputError(
                        f"{path}: missing columns: {', '.join(missing_columns)}"
                    )
                for line_number, raw_row in enumerate(reader, start=2):
                    values = {
                        column: (raw_row.get(column) or "") for column in INPUT_COLUMNS
                    }
                    submission_id = values["submission_id"].strip()
                    if not submission_id:
                        raise InputError(f"{path}:{line_number}: blank submission_id")
                    if submission_id in seen_ids:
                        raise InputError(
                            f"{path}:{line_number}: duplicate submission_id {submission_id}"
                        )
                    seen_ids.add(submission_id)
                    submissions.append(Submission(path.name, values))
        except UnicodeDecodeError as exc:
            raise InputError(f"{path}: input must be UTF-8 encoded") from exc
        except OSError as exc:
            raise InputError(f"Could not read {path}: {exc}") from exc
    return submissions


def validate_submission(
    submission: Submission,
    reference: ReferenceData,
    classifications: dict,
    category_name_by_id: dict[int, str],
) -> tuple[ValidMerchant | None, list[str], str]:
    values = submission.values
    reasons: list[str] = []

    for field in REQUIRED_FIELDS:
        if not values[field].strip():
            reasons.append(f"Missing required field: {field}")

    merchant_identity = identity_key(values["merchant_name"])
    merchant_name = normalise_merchant_name(values["merchant_name"])

    region_key = identity_key(values["region"])
    region_pic = reference.regions_by_key.get(region_key)
    if values["region"].strip() and region_pic is None:
        reasons.append(f"Invalid region: {values['region'].strip()}")

    email = values["contact_email"].strip().lower()
    if values["contact_email"].strip() and not EMAIL_RE.fullmatch(email):
        reasons.append("Invalid contact email format")

    phone = normalise_phone(values["contact_phone"])
    if values["contact_phone"].strip() and len(phone) < 9:
        reasons.append("Contact phone has fewer than 9 digits after normalisation")

    parsed_date = None
    if values["registration_date"].strip():
        parsed_date = parse_registration_date(values["registration_date"])
        if parsed_date is None:
            reasons.append("Registration date is invalid or uses an unsupported format")
        elif parsed_date > REFERENCE_DATE:
            reasons.append(
                f"Registration date is after the reference date {REFERENCE_DATE.isoformat()}"
            )

    classification = None
    category_text = values["business_category_freetext"]
    if category_text.strip():
        classification = classifications.get(normalize_category_text(category_text))
        if classification is None:
            raise ClassificationError(
                f"No classification result for description: {category_text!r}"
            )
        if classification.status == "unmappable":
            reasons.append(
                f"Business category cannot be mapped: {category_text.strip()}"
            )

    existing_id = values["existing_merchant_id"].strip()
    if existing_id and existing_id in reference.existing_ids:
        reasons.append(f"Merchant is already onboarded with ID {existing_id}")
    if merchant_identity and merchant_identity in reference.existing_names:
        reasons.append("Merchant is already onboarded based on merchant name")

    pic_email = region_pic.pic_email if region_pic else ""
    if reasons:
        return None, reasons, pic_email

    if classification is None or classification.category_id is None:
        raise ClassificationError("A valid submission is missing a mapped category.")
    if parsed_date is None or region_pic is None:
        raise InputError("Internal validation error while constructing a valid merchant.")

    return (
        ValidMerchant(
            submission_id=values["submission_id"].strip(),
            merchant_name=merchant_name,
            merchant_identity=merchant_identity,
            canonical_category=category_name_by_id[classification.category_id],
            region=region_pic.region,
            contact_phone=phone,
            contact_email=email,
            registration_date=parsed_date.isoformat(),
            region_pic_email=pic_email,
        ),
        [],
        pic_email,
    )


def deduplicate_merchants(merchants: Iterable[ValidMerchant]) -> list[dict[str, object]]:
    groups: dict[tuple[str, str], list[ValidMerchant]] = defaultdict(list)
    for merchant in merchants:
        groups[(merchant.merchant_identity, merchant.region)].append(merchant)

    output: list[dict[str, object]] = []
    for group in groups.values():
        ordered = sorted(group, key=lambda item: item.submission_id)
        winner = ordered[0]
        output.append(
            {
                "merchant_name": winner.merchant_name,
                "canonical_category": winner.canonical_category,
                "region": winner.region,
                "contact_phone": winner.contact_phone,
                "contact_email": winner.contact_email,
                "registration_date": winner.registration_date,
                "region_pic_email": winner.region_pic_email,
                "source_submission_id": winner.submission_id,
                "duplicates_collapsed": len(ordered) - 1,
            }
        )
    return sorted(output, key=lambda row: str(row["source_submission_id"]))


def write_csv(path: str | Path, columns: Sequence[str], rows: Iterable[dict]) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list(columns), extrasaction="ignore", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)


def consolidate(
    input_paths: Sequence[str | Path],
    reference_db: str | Path,
    cache_db: str | Path,
    clean_output: str | Path,
    errors_output: str | Path,
    batch_size: int = 50,
    endpoint: str = DEFAULT_ENDPOINT,
    model: str = DEFAULT_MODEL,
) -> dict[str, int]:
    reference = load_reference_data(reference_db)
    submissions = read_submissions(input_paths)

    category_descriptions = [
        item.values["business_category_freetext"]
        for item in submissions
        if item.values["business_category_freetext"].strip()
    ]
    classifications, classification_metrics = classify_descriptions(
        original_texts=category_descriptions,
        categories=reference.categories,
        cache_path=cache_db,
        batch_size=batch_size,
        endpoint=endpoint,
        model=model,
    )
    category_name_by_id = {
        category.category_id: category.canonical_name for category in reference.categories
    }

    valid_merchants: list[ValidMerchant] = []
    error_rows: list[dict[str, str]] = []
    for submission in submissions:
        merchant, reasons, pic_email = validate_submission(
            submission, reference, classifications, category_name_by_id
        )
        if merchant is not None:
            valid_merchants.append(merchant)
        else:
            error_rows.append(
                {
                    "submission_id": submission.values["submission_id"].strip(),
                    "source_file": submission.source_file,
                    "merchant_name": compact_whitespace(
                        submission.values["merchant_name"]
                    ),
                    "region": compact_whitespace(submission.values["region"]),
                    "region_pic_email": pic_email,
                    "rejection_reasons": "; ".join(reasons),
                }
            )

    clean_rows = deduplicate_merchants(valid_merchants)
    error_rows.sort(key=lambda row: row["submission_id"])
    write_csv(clean_output, CLEAN_COLUMNS, clean_rows)
    write_csv(errors_output, ERROR_COLUMNS, error_rows)

    return {
        "input_rows": len(submissions),
        "valid_rows_before_deduplication": len(valid_merchants),
        "clean_rows": len(clean_rows),
        "error_rows": len(error_rows),
        "duplicates_collapsed": len(valid_merchants) - len(clean_rows),
        **classification_metrics,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate, classify, and consolidate partner merchant submissions."
    )
    parser.add_argument(
        "--input-glob",
        default="data/submissions_partner*.csv",
        help="Glob for partner CSV files (default: data/submissions_partner*.csv)",
    )
    parser.add_argument("--reference-db", default="reference.db")
    parser.add_argument("--cache-db", default="classification_cache.db")
    parser.add_argument("--clean-output", default="clean.csv")
    parser.add_argument("--errors-output", default="errors.csv")
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    input_paths = sorted(glob.glob(args.input_glob))
    if not input_paths:
        print(f"Error: no input files matched {args.input_glob!r}", file=sys.stderr)
        return 2

    try:
        metrics = consolidate(
            input_paths=input_paths,
            reference_db=args.reference_db,
            cache_db=args.cache_db,
            clean_output=args.clean_output,
            errors_output=args.errors_output,
            batch_size=args.batch_size,
            endpoint=args.endpoint,
            model=args.model,
        )
    except (InputError, ClassificationError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    print("Consolidation completed")
    for name, value in metrics.items():
        print(f"  {name}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
