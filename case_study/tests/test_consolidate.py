import csv
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from classification import (
    Category,
    Classification,
    ClassificationCache,
    ClassificationError,
    GitHubModelsClassifier,
    normalize_category_text,
    taxonomy_version,
)
from consolidate import consolidate, normalise_phone, parse_registration_date


class NormalisationTests(unittest.TestCase):
    def test_malaysian_phone_normalisation(self):
        self.assertEqual(normalise_phone("+60 12-345 6789"), "0123456789")
        self.assertEqual(normalise_phone("60-12-345-6789"), "0123456789")
        self.assertEqual(normalise_phone("012 345 6789"), "0123456789")

    def test_supported_and_impossible_dates(self):
        self.assertEqual(parse_registration_date("1/6/2026").isoformat(), "2026-06-01")
        self.assertEqual(parse_registration_date("2026-05-31").isoformat(), "2026-05-31")
        self.assertIsNone(parse_registration_date("31/02/2026"))

    def test_category_cache_key_is_conservative(self):
        self.assertEqual(
            normalize_category_text("  LAPTOP   Servicing "), "laptop servicing"
        )


class CacheTests(unittest.TestCase):
    def test_cache_is_scoped_to_taxonomy(self):
        categories = [Category(1, "Food & Beverage")]
        version = taxonomy_version(categories)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cache.db"
            with ClassificationCache(path) as cache:
                item = Classification("kopitiam", 1, "mapped", "test")
                cache.put_many(
                    [item],
                    {"kopitiam": "kopitiam"},
                    version,
                    model="test-model",
                )
                self.assertIn("kopitiam", cache.get_many(["kopitiam"], version))
                self.assertEqual(cache.get_many(["kopitiam"], "different"), {})


class ModelResponseTests(unittest.TestCase):
    def test_rejects_category_absent_from_reference_database(self):
        with self.assertRaises(ClassificationError):
            GitHubModelsClassifier._validate_response(
                {"results": [{"id": 1, "status": "mapped", "category_id": 99}]},
                requested_ids={1},
                allowed_category_ids={1, 2},
                key_by_id={1: "kopitiam"},
            )

    def test_accepts_mapped_and_unmappable_results(self):
        results = GitHubModelsClassifier._validate_response(
            {
                "results": [
                    {"id": 1, "status": "mapped", "category_id": 1},
                    {"id": 2, "status": "unmappable", "category_id": None},
                ]
            },
            requested_ids={1, 2},
            allowed_category_ids={1},
            key_by_id={1: "kopitiam", 2: "other"},
        )
        self.assertEqual([item.status for item in results], ["mapped", "unmappable"])


class EndToEndTests(unittest.TestCase):
    @staticmethod
    def _create_reference_db(path: Path) -> None:
        connection = sqlite3.connect(path)
        connection.executescript(
            """
            CREATE TABLE categories (
                category_id INTEGER PRIMARY KEY,
                canonical_name TEXT NOT NULL UNIQUE
            );
            CREATE TABLE region_pic (
                region TEXT PRIMARY KEY,
                pic_name TEXT NOT NULL,
                pic_email TEXT NOT NULL
            );
            CREATE TABLE existing_merchants (
                merchant_id TEXT PRIMARY KEY,
                merchant_name TEXT NOT NULL
            );
            INSERT INTO categories VALUES (1, 'Food & Beverage');
            INSERT INTO region_pic VALUES (
                'Central', 'Test PIC', 'central@example.test'
            );
            INSERT INTO existing_merchants VALUES ('M0001', 'Known Merchant');
            """
        )
        connection.commit()
        connection.close()

    @staticmethod
    def _write_input(path: Path) -> None:
        columns = [
            "submission_id",
            "merchant_name",
            "business_category_freetext",
            "region",
            "contact_phone",
            "contact_email",
            "registration_date",
            "existing_merchant_id",
        ]
        rows = [
            [
                "A001",
                "  bagus cafe  ",
                "kopitiam",
                "central",
                "+60 12-345 6789",
                "OWNER@EXAMPLE.COM",
                "1/6/2026",
                "",
            ],
            [
                "B001",
                "BAGUS CAFE",
                "kopitiam",
                "Central",
                "0123456789",
                "other@example.com",
                "2026-05-01",
                "",
            ],
            [
                "C001",
                "Known Merchant",
                "other",
                "Unknown",
                "123",
                "bad-email",
                "31/02/2026",
                "M0001",
            ],
        ]
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(columns)
            writer.writerows(rows)

    def test_end_to_end_validation_and_deduplication(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference_db = root / "reference.db"
            input_csv = root / "submissions.csv"
            clean_csv = root / "clean.csv"
            errors_csv = root / "errors.csv"
            self._create_reference_db(reference_db)
            self._write_input(input_csv)

            classifications = {
                "kopitiam": Classification("kopitiam", 1, "mapped", "test"),
                "other": Classification("other", None, "unmappable", "test"),
            }
            metrics = {
                "unique_descriptions": 2,
                "cache_hits": 2,
                "llm_descriptions": 0,
                "llm_batches": 0,
            }
            with patch(
                "consolidate.classify_descriptions",
                return_value=(classifications, metrics),
            ):
                result = consolidate(
                    [input_csv],
                    reference_db,
                    root / "cache.db",
                    clean_csv,
                    errors_csv,
                )

            self.assertEqual(result["clean_rows"], 1)
            self.assertEqual(result["duplicates_collapsed"], 1)
            self.assertEqual(result["error_rows"], 1)

            with clean_csv.open(encoding="utf-8", newline="") as handle:
                clean_rows = list(csv.DictReader(handle))
            self.assertEqual(clean_rows[0]["merchant_name"], "Bagus Cafe")
            self.assertEqual(clean_rows[0]["contact_phone"], "0123456789")
            self.assertEqual(clean_rows[0]["duplicates_collapsed"], "1")

            with errors_csv.open(encoding="utf-8", newline="") as handle:
                error_rows = list(csv.DictReader(handle))
            reasons = error_rows[0]["rejection_reasons"]
            self.assertIn("Invalid region", reasons)
            self.assertIn("Invalid contact email", reasons)
            self.assertIn("fewer than 9 digits", reasons)
            self.assertIn("already onboarded", reasons)
            self.assertIn("cannot be mapped", reasons)


if __name__ == "__main__":
    unittest.main()
