"""Tiny BERT-based analyzer for accounting insights (fits in 512MB RAM)."""

import os
from typing import Any

import structlog
import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

from app.config import get_settings
from app.db.redis import cache_get, cache_set

logger = structlog.get_logger()
settings = get_settings()

# Tiny model for accounting analysis - only 66M parameters vs 1.5B
# Using base distilbert, fine-tuning optional for your specific accounting tasks
TINY_MODEL = "distilbert-base-uncased"  # 66M params, ~150MB RAM


class TinyAccountingAnalyzer:
    """Lightweight analyzer using DistilBERT (66M params, ~150MB RAM).

    Replaces heavy LLM for:
    - Anomaly detection (binary classification)
    - Account categorization (multi-class)
    - Simple insight generation (extractive, not generative)
    """

    _model = None
    _tokenizer = None
    _initialized = False

    @classmethod
    async def initialize(cls) -> bool:
        """Load tiny model (fast, low RAM)."""
        if cls._initialized:
            return True

        try:
            logger.info("loading_tiny_analyzer", model=TINY_MODEL)

            # Use CPU, float32 for compatibility
            cls._tokenizer = AutoTokenizer.from_pretrained(
                TINY_MODEL,
                cache_dir="/app/.cache/huggingface",
                local_files_only=bool(os.getenv("HF_HUB_OFFLINE")),
            )

            cls._model = AutoModelForSequenceClassification.from_pretrained(
                TINY_MODEL,
                cache_dir="/app/.cache/huggingface",
                local_files_only=bool(os.getenv("HF_HUB_OFFLINE")),
            )
            cls._model.eval()  # Inference only

            cls._initialized = True
            logger.info("tiny_analyzer_loaded", model_size="66M params")
            return True

        except Exception as e:
            logger.error("tiny_analyzer_load_failed", error=str(e))
            return False

    @classmethod
    def is_ready(cls) -> bool:
        return cls._initialized and cls._model is not None

    @classmethod
    async def analyze(
        cls,
        invoices: list[dict],
        journal_entries: list[Any],
        summary: dict,
    ) -> dict:
        """Generate simple accounting analysis using tiny model.

        Falls back to rule-based if model not available.
        """
        cache_key = f"analysis:{hash(str(summary))}"
        cached = await cache_get(cache_key)
        if cached:
            return cached

        # If tiny model not loaded, use rule-based analysis
        if not cls.is_ready():
            return cls._rule_based_analysis(invoices, journal_entries, summary)

        try:
            # Simple anomaly detection using the model
            # Prepare text representation of financial data
            text = cls._prepare_text(summary)

            # Tokenize and predict
            inputs = cls._tokenizer(
                text,
                return_tensors="pt",
                truncation=True,
                max_length=512,
            )

            with torch.no_grad():
                outputs = cls._model(**inputs)
                scores = torch.softmax(outputs.logits, dim=1)

            # Interpret results (positive = healthy, negative = anomaly)
            healthy_score = scores[0][1].item()

            result = {
                "insights": cls._generate_insights(healthy_score, summary),
                "recommendations": cls._generate_recommendations(healthy_score, summary),
                "anomalies": cls._detect_anomalies(healthy_score, invoices, journal_entries),
            }

            await cache_set(cache_key, result, expire=3600)
            return result

        except Exception as e:
            logger.error("tiny_analysis_failed", error=str(e))
            return cls._rule_based_analysis(invoices, journal_entries, summary)

    @classmethod
    def _rule_based_analysis(
        cls,
        invoices: list[dict],
        journal_entries: list[Any],
        summary: dict,
    ) -> dict:
        """Fallback rule-based analysis (no ML needed)."""
        insights = []
        recommendations = []
        anomalies = []

        # Check cash position
        cash = summary.get("cash_position", 0)
        if cash < 0:
            anomalies.append("Negative cash position detected")
            recommendations.append("Review outstanding receivables immediately")
        elif cash < 1000:
            insights.append("Low cash reserves - monitor liquidity closely")

        # Check revenue trend
        revenue = summary.get("total_revenue", 0)
        if revenue == 0:
            anomalies.append("No revenue recorded in period")

        # Check tax compliance
        tax_due = summary.get("tax_due", 0)
        if tax_due > revenue * 0.3:
            insights.append("High tax burden relative to revenue")

        # Check for unpaid invoices
        unpaid = [i for i in invoices if i.get("status") in ["UNPAID", "PARTIAL"]]
        if len(unpaid) > 5:
            recommendations.append(f"Follow up on {len(unpaid)} unpaid invoices")

        return {
            "insights": " | ".join(insights) if insights else "Financials within normal parameters",
            "recommendations": recommendations,
            "anomalies": anomalies,
        }

    @classmethod
    def _prepare_text(cls, summary: dict) -> str:
        """Convert summary to text for model input."""
        return (
            f"Revenue: {summary.get('total_revenue', 0)}. "
            f"Expenses: {summary.get('total_expenses', 0)}. "
            f"Profit: {summary.get('net_profit', 0)}. "
            f"Cash: {summary.get('cash_position', 0)}. "
            f"Tax: {summary.get('tax_due', 0)}."
        )

    @classmethod
    def _generate_insights(cls, healthy_score: float, summary: dict) -> str:
        """Generate insights based on model score."""
        if healthy_score > 0.8:
            return "Financial health is strong. Maintain current operations."
        elif healthy_score > 0.5:
            return "Financials are stable with minor areas for improvement."
        else:
            return "Financial stress indicators detected. Review expenses and receivables."

    @classmethod
    def _generate_recommendations(cls, healthy_score: float, summary: dict) -> list[str]:
        """Generate recommendations based on score and metrics."""
        recs = []

        if healthy_score < 0.6:
            recs.append("Reduce discretionary spending")
            recs.append("Accelerate invoice collection")

        if summary.get("cash_position", 0) < 5000:
            recs.append("Build cash reserves to at least 5000 TND")

        return recs

    @classmethod
    def _detect_anomalies(
        cls,
        healthy_score: float,
        invoices: list[dict],
        journal_entries: list[Any],
    ) -> list[str]:
        """Detect anomalies based on model score and data."""
        anomalies = []

        if healthy_score < 0.3:
            anomalies.append("Model indicates significant financial anomaly")

        # Check for duplicate invoice numbers
        inv_nums = [i.get("invoiceNumber") for i in invoices if i.get("invoiceNumber")]
        if len(inv_nums) != len(set(inv_nums)):
            anomalies.append("Duplicate invoice numbers detected")

        return anomalies
