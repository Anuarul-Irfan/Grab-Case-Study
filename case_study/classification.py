"""Category classification with exact caching and batched GitHub Models calls."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence



PROMPT_VERSION = "2026-07-12-v1"
DEFAULT_ENDPOINT = "https://models.github.ai/inference"
DEFAULT_MODEL = "openai/gpt-4.1-mini"


class ClassificationError(RuntimeError):
    """Raised when unresolved descriptions cannot be classified safely."""


@dataclass(frozen=True)
class Category:
    category_id: int
    canonical_name: str


@dataclass(frozen=True)
class Classification:
    normalized_text: str
    category_id: int | None
    status: str
    source: str


def normalize_category_text(value: str) -> str:
    """Return a conservative exact-cache key without changing semantics."""
    normalized = unicodedata.normalize("NFKC", value)
    return " ".join(normalized.strip().casefold().split())


def taxonomy_version(categories: Sequence[Category]) -> str:
    payload = json.dumps(
        sorted(
            ((category.category_id, category.canonical_name) for category in categories),
            key=lambda item: item[0],
        ),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ClassificationCache:
    """Persistent exact-match cache stored separately from reference.db."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS classifications (
                taxonomy_version TEXT NOT NULL,
                normalized_text TEXT NOT NULL,
                original_text TEXT NOT NULL,
                category_id INTEGER,
                status TEXT NOT NULL CHECK (status IN ('mapped', 'unmappable')),
                source TEXT NOT NULL,
                model TEXT,
                prompt_version TEXT NOT NULL,
                reviewed INTEGER NOT NULL DEFAULT 0 CHECK (reviewed IN (0, 1)),
                created_at TEXT NOT NULL,
                PRIMARY KEY (taxonomy_version, normalized_text),
                CHECK (
                    (status = 'mapped' AND category_id IS NOT NULL)
                    OR (status = 'unmappable' AND category_id IS NULL)
                )
            )
            """
        )
        self.connection.commit()

    def get_many(
        self, texts: Iterable[str], current_taxonomy: str
    ) -> dict[str, Classification]:
        keys = sorted(set(texts))
        if not keys:
            return {}

        results: dict[str, Classification] = {}
        chunk_size = 500
        for start in range(0, len(keys), chunk_size):
            chunk = keys[start : start + chunk_size]
            placeholders = ",".join("?" for _ in chunk)
            rows = self.connection.execute(
                f"""
                SELECT normalized_text, category_id, status, source
                FROM classifications
                WHERE taxonomy_version = ?
                  AND normalized_text IN ({placeholders})
                """,
                [current_taxonomy, *chunk],
            ).fetchall()
            for row in rows:
                results[row["normalized_text"]] = Classification(
                    normalized_text=row["normalized_text"],
                    category_id=row["category_id"],
                    status=row["status"],
                    source=row["source"],
                )
        return results

    def put_many(
        self,
        classifications: Iterable[Classification],
        original_by_key: dict[str, str],
        current_taxonomy: str,
        model: str | None,
        reviewed: bool = False,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        rows = [
            (
                current_taxonomy,
                item.normalized_text,
                original_by_key[item.normalized_text],
                item.category_id,
                item.status,
                item.source,
                model,
                PROMPT_VERSION,
                int(reviewed),
                now,
            )
            for item in classifications
        ]
        if not rows:
            return
        with self.connection:
            self.connection.executemany(
                """
                INSERT INTO classifications (
                    taxonomy_version, normalized_text, original_text, category_id,
                    status, source, model, prompt_version, reviewed, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(taxonomy_version, normalized_text) DO UPDATE SET
                    original_text = excluded.original_text,
                    category_id = excluded.category_id,
                    status = excluded.status,
                    source = excluded.source,
                    model = excluded.model,
                    prompt_version = excluded.prompt_version,
                    reviewed = excluded.reviewed,
                    created_at = excluded.created_at
                """,
                rows,
            )

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "ClassificationCache":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


class GitHubModelsClassifier:
    """Classify batches using the GitHub Models Azure AI Inference endpoint."""

    SYSTEM_PROMPT = """You classify short merchant business descriptions.
Select exactly one category from the categories supplied in the user message.
The supplied categories are the only allowed mapped results.
Descriptions may be English, Malay, another language, or mixed-language.
Use status 'unmappable' when the description is vague, ambiguous, or does not
fit any supplied category. Do not guess. Return only valid JSON in the exact
shape requested, with no markdown or explanatory text."""

    def __init__(
        self,
        endpoint: str = DEFAULT_ENDPOINT,
        model: str = DEFAULT_MODEL,
        token: str | None = None,
        max_retries: int = 3,
    ) -> None:
        self.endpoint = endpoint
        self.model = model
        self.token = token or os.getenv("GITHUB_TOKEN")
        self.max_retries = max_retries
        self._client = None

    def _get_client(self):
        if not self.token:
            raise ClassificationError(
                "GITHUB_TOKEN is required because uncached category descriptions "
                "need classification. The token must have models:read permission."
            )
        if self._client is None:
            try:
                from azure.ai.inference import ChatCompletionsClient
                from azure.core.credentials import AzureKeyCredential
            except ImportError as exc:
                raise ClassificationError(
                    "azure-ai-inference is required for uncached descriptions. "
                    "Install dependencies with: pip install -r requirements.txt"
                ) from exc
            self._client = ChatCompletionsClient(
                endpoint=self.endpoint,
                credential=AzureKeyCredential(self.token),
            )
        return self._client

    @staticmethod
    def _parse_json(content: str) -> dict:
        cleaned = content.strip()
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            cleaned = "\n".join(lines)
        try:
            result = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise ClassificationError("The model returned malformed JSON.") from exc
        if not isinstance(result, dict):
            raise ClassificationError("The model response must be a JSON object.")
        return result

    @staticmethod
    def _validate_response(
        payload: dict,
        requested_ids: set[int],
        allowed_category_ids: set[int],
        key_by_id: dict[int, str],
    ) -> list[Classification]:
        raw_results = payload.get("results")
        if not isinstance(raw_results, list):
            raise ClassificationError("The model response is missing a results list.")

        seen: set[int] = set()
        validated: list[Classification] = []
        for result in raw_results:
            if not isinstance(result, dict):
                raise ClassificationError("Every model result must be an object.")
            item_id = result.get("id")
            if not isinstance(item_id, int) or item_id not in requested_ids:
                raise ClassificationError("The model returned an unexpected item id.")
            if item_id in seen:
                raise ClassificationError("The model returned a duplicate item id.")
            seen.add(item_id)

            status = result.get("status")
            category_id = result.get("category_id")
            if status == "mapped":
                if not isinstance(category_id, int) or category_id not in allowed_category_ids:
                    raise ClassificationError(
                        "The model returned a category id absent from reference.db."
                    )
            elif status == "unmappable":
                if category_id is not None:
                    raise ClassificationError(
                        "An unmappable model result must have a null category_id."
                    )
            else:
                raise ClassificationError("The model returned an invalid status.")

            validated.append(
                Classification(
                    normalized_text=key_by_id[item_id],
                    category_id=category_id,
                    status=status,
                    source="llm",
                )
            )

        if seen != requested_ids:
            raise ClassificationError("The model omitted one or more requested items.")
        return validated

    def classify_batch(
        self,
        descriptions: Sequence[tuple[str, str]],
        categories: Sequence[Category],
    ) -> list[Classification]:
        if not descriptions:
            return []

        key_by_id = {index: key for index, (key, _) in enumerate(descriptions, start=1)}
        request_payload = {
            "categories": [
                {"id": category.category_id, "name": category.canonical_name}
                for category in categories
            ],
            "items": [
                {"id": index, "text": original}
                for index, (_, original) in enumerate(descriptions, start=1)
            ],
            "required_response": {
                "results": [
                    {
                        "id": "integer item id",
                        "status": "mapped or unmappable",
                        "category_id": "allowed integer category id, or null",
                    }
                ]
            },
        }

        try:
            from azure.ai.inference.models import SystemMessage, UserMessage
            from azure.core.exceptions import HttpResponseError
        except ImportError as exc:
            raise ClassificationError(
                "azure-ai-inference is required for uncached descriptions."
            ) from exc

        client = self._get_client()
        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                response = client.complete(
                    messages=[
                        SystemMessage(self.SYSTEM_PROMPT),
                        UserMessage(
                            json.dumps(
                                request_payload,
                                ensure_ascii=False,
                                separators=(",", ":"),
                            )
                        ),
                    ],
                    model=self.model,
                )
                content = response.choices[0].message.content
                if not content:
                    raise ClassificationError("The model returned an empty response.")
                payload = self._parse_json(content)
                return self._validate_response(
                    payload=payload,
                    requested_ids=set(key_by_id),
                    allowed_category_ids={item.category_id for item in categories},
                    key_by_id=key_by_id,
                )
            except HttpResponseError as exc:
                last_error = exc
                retryable = exc.status_code == 429 or (exc.status_code or 0) >= 500
                if not retryable or attempt == self.max_retries - 1:
                    break
            except (ClassificationError, IndexError, AttributeError) as exc:
                last_error = exc
                if attempt == self.max_retries - 1:
                    break
            time.sleep(2**attempt)

        raise ClassificationError(
            f"Classification batch failed after {self.max_retries} attempts: {last_error}"
        ) from last_error

    def close(self) -> None:
        if self._client is not None:
            self._client.close()


def classify_descriptions(
    original_texts: Iterable[str],
    categories: Sequence[Category],
    cache_path: str | Path,
    batch_size: int = 50,
    endpoint: str = DEFAULT_ENDPOINT,
    model: str = DEFAULT_MODEL,
    token: str | None = None,
) -> tuple[dict[str, Classification], dict[str, int]]:
    """Resolve descriptions through the exact cache, then batched LLM calls."""
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")

    original_by_key: dict[str, str] = {}
    for original in original_texts:
        key = normalize_category_text(original)
        if key:
            original_by_key.setdefault(key, original.strip())

    current_taxonomy = taxonomy_version(categories)
    classifier = GitHubModelsClassifier(endpoint=endpoint, model=model, token=token)
    try:
        with ClassificationCache(cache_path) as cache:
            resolved = cache.get_many(original_by_key, current_taxonomy)
            misses = sorted(set(original_by_key) - set(resolved))
            for start in range(0, len(misses), batch_size):
                batch_keys = misses[start : start + batch_size]
                batch = [(key, original_by_key[key]) for key in batch_keys]
                new_results = classifier.classify_batch(batch, categories)
                cache.put_many(
                    classifications=new_results,
                    original_by_key=original_by_key,
                    current_taxonomy=current_taxonomy,
                    model=model,
                )
                resolved.update({item.normalized_text: item for item in new_results})
    finally:
        classifier.close()

    metrics = {
        "unique_descriptions": len(original_by_key),
        "cache_hits": len(original_by_key) - len(misses),
        "llm_descriptions": len(misses),
        "llm_batches": (len(misses) + batch_size - 1) // batch_size,
    }
    return resolved, metrics
