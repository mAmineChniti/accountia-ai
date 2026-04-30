"""Tiny analyzer wrapper that prefers a TensorFlow-based implementation.

This module keeps the existing `TinyAccountingAnalyzer` import surface but
replaces the heavy `transformers/torch` dependency with a lightweight
TensorFlow/Keras-based analyzer implemented in `tf_analyzer.py`. When
TensorFlow is unavailable or a model is not present, it falls back to a
rule-based analysis identical to the previous implementation.
"""

from typing import Any

import structlog

from app.db.redis import cache_get, cache_set
from app.services.tf_analyzer import TFAccountingAnalyzer

logger = structlog.get_logger()


class TinyAccountingAnalyzer:
    @classmethod
    def is_ready(cls) -> bool:
        return TFAccountingAnalyzer.is_ready()

    @classmethod
    async def initialize(cls) -> bool:
        return TFAccountingAnalyzer.load_model()

    @classmethod
    async def analyze(cls, invoices: list[dict], journal_entries: list[Any], summary: dict) -> dict:
        cache_key = f"analysis:{hash(str(summary))}"
        cached = await cache_get(cache_key)
        if cached:
            return cached

        result = await TFAccountingAnalyzer.analyze(invoices, journal_entries, summary)
        try:
            await cache_set(cache_key, result, expire=3600)
        except Exception:
            logger.exception("cache_set_failed")
        return result

    @classmethod
    def get_model_info(cls) -> dict:
        """Return lightweight model info for health checks and diagnostics."""
        ready = TFAccountingAnalyzer.is_ready()
        return {
            "name": "tiny_tensorflow_analyzer",
            "ready": ready,
            "using_tensorflow": True,
            "model_path": bool(TFAccountingAnalyzer.__dict__.get("_model")),
        }
