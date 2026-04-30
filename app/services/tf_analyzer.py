"""Lightweight TensorFlow-based analyzer for accounting insights.

This implements a small Keras model scaffold for binary anomaly detection
and simple scoring. Training utilities are included but optional; the
service uses a rule-based fallback when no trained model is present.

Designed to replace the transformers/torch-based tiny analyzer to avoid
large HuggingFace model downloads and provide an on-device lightweight
alternative built with TensorFlow/Keras.
"""

from __future__ import annotations

import os
from typing import Any

import structlog

logger = structlog.get_logger()

MODEL_PATH = "/app/.cache/tf_analyzer/model.json"
WEIGHTS_PATH = "/app/.cache/tf_analyzer/weights.h5"


class TFAccountingAnalyzer:
    """Simple TF-based analyzer. Uses a tiny dense network over engineered features.

    This is intentionally small (KBs-MBs) and fast on CPU. It expects a numeric
    summary dict and returns the same output shape used by the existing analyzer
    interface: {insights, recommendations, anomalies}.
    """

    _ready = False

    @classmethod
    def is_ready(cls) -> bool:
        return cls._ready and os.path.exists(MODEL_PATH)

    @classmethod
    def load_model(cls) -> bool:
        # Lightweight: we don't require tensorflow at import time for faster cold-start
        try:
            from tensorflow import keras
        except Exception as e:
            logger.info("tf_not_available", error=str(e))
            return False

        if not os.path.exists(MODEL_PATH) or not os.path.exists(WEIGHTS_PATH):
            logger.info("tf_model_missing", model_path=MODEL_PATH)
            return False

        try:
            with open(MODEL_PATH) as f:
                model_json = f.read()
            model = keras.models.model_from_json(model_json)
            model.load_weights(WEIGHTS_PATH)
            model.trainable = False
            cls._model = model
            cls._ready = True
            logger.info("tf_analyzer_loaded")
            return True
        except Exception as e:
            logger.exception("tf_model_load_failed", error=str(e))
            return False

    @classmethod
    async def analyze(cls, invoices: list[dict], journal_entries: list[Any], summary: dict) -> dict:
        # If model not ready, fall back to a rule-based analyzer
        if not cls.is_ready():
            cls.load_model()  # attempt load
        if not cls.is_ready():
            return cls._rule_based_analysis(invoices, journal_entries, summary)

        try:
            import numpy as np

            features = cls._features_from_summary(summary)
            x = np.asarray([features], dtype=np.float32)
            preds = cls._model.predict(x)
            score = float(preds[0][0])

            insights = cls._generate_insights(score, summary)
            recs = cls._generate_recommendations(score, summary)
            anomalies = cls._detect_anomalies(score, invoices, journal_entries)

            return {"insights": insights, "recommendations": recs, "anomalies": anomalies}
        except Exception as e:
            logger.exception("tf_analyze_failed", error=str(e))
            return cls._rule_based_analysis(invoices, journal_entries, summary)

    @classmethod
    def _features_from_summary(cls, summary: dict) -> list[float]:
        # Basic engineered features: revenue, expenses, net margin, AR/AP ratio, cash
        revenue = float(summary.get("total_revenue", 0) or 0)
        expenses = float(summary.get("total_expenses", 0) or 0)
        net = float(summary.get("net_profit", revenue - expenses) or 0)
        cash = float(summary.get("cash_position", 0) or 0)
        ar = float(summary.get("accounts_receivable", 0) or 0)
        ap = float(summary.get("accounts_payable", 0) or 0)

        margin = net / revenue if revenue > 0 else 0.0
        ar_ap = ar / (ap + 1e-6)

        return [revenue, expenses, net, cash, margin, ar_ap]

    @classmethod
    def _rule_based_analysis(cls, invoices: list[dict], journal_entries: list[Any], summary: dict) -> dict:
        insights = []
        recommendations = []
        anomalies = []

        cash = float(summary.get("cash_position", 0) or 0)
        if cash < 0:
            anomalies.append("Negative cash position detected")
            recommendations.append("Review outstanding receivables immediately")
        elif cash < 1000:
            insights.append("Low cash reserves - monitor liquidity closely")

        revenue = float(summary.get("total_revenue", 0) or 0)
        if revenue == 0:
            anomalies.append("No revenue recorded in period")

        unpaid = [i for i in invoices if i.get("status") in ["UNPAID", "PARTIAL"]]
        if len(unpaid) > 5:
            recommendations.append(f"Follow up on {len(unpaid)} unpaid invoices")

        return {
            "insights": " | ".join(insights) if insights else "Financials within normal parameters",
            "recommendations": recommendations,
            "anomalies": anomalies,
        }

    @classmethod
    def _generate_insights(cls, score: float, summary: dict) -> str:
        if score > 0.8:
            return "Financial health is strong. Maintain current operations."
        elif score > 0.5:
            return "Financials are stable with minor areas for improvement."
        else:
            return "Financial stress indicators detected. Review expenses and receivables."

    @classmethod
    def _generate_recommendations(cls, score: float, summary: dict) -> list[str]:
        recs = []
        if score < 0.6:
            recs.append("Reduce discretionary spending")
            recs.append("Accelerate invoice collection")
        if float(summary.get("cash_position", 0) or 0) < 5000:
            recs.append("Build cash reserves to at least 5000 TND")
        return recs

    @classmethod
    def _detect_anomalies(cls, score: float, invoices: list[dict], journal_entries: list[Any]) -> list[str]:
        anomalies = []
        if score < 0.3:
            anomalies.append("Model indicates significant financial anomaly")
        inv_nums = [i.get("invoiceNumber") for i in invoices if i.get("invoiceNumber")]
        if len(inv_nums) != len(set(inv_nums)):
            anomalies.append("Duplicate invoice numbers detected")
        return anomalies
