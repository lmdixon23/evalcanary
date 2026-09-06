"""Bounded evaluator-assurance processing for the local v0.2 development line."""

from __future__ import annotations

from .engine import build_report
from .renderers import write_report_bundle
from .review_queue import build_review_queue, verify_review_queue_binding
from .schema import AssuranceArtifact, Limits, load_artifact, load_contract

ASSURANCE_ENGINE_VERSION = "0.2.0.dev0"

__all__ = [
    "ASSURANCE_ENGINE_VERSION",
    "AssuranceArtifact",
    "Limits",
    "build_report",
    "build_review_queue",
    "load_artifact",
    "load_contract",
    "verify_review_queue_binding",
    "write_report_bundle",
]
