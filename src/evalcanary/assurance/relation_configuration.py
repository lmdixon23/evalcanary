"""Typed, string-free references to validated invariance relation semantics."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, TypedDict


class EmptyConfiguration(TypedDict):
    pass


class ScoreConfiguration(TypedDict):
    absolute_tolerance: Decimal


class PreferenceConfiguration(TypedDict):
    first_label_index: int
    second_label_index: int
    tie_label_index: int | None


RelationConfiguration = (
    EmptyConfiguration | ScoreConfiguration | PreferenceConfiguration
)


def relation_configuration(
    group: dict[str, Any], judgment_spec: dict[str, Any]
) -> RelationConfiguration:
    """Transform a validated declaration without copying or redacting labels."""

    parameters = group["relation_parameters"]
    if group["expected_relation"] == "same_label":
        return EmptyConfiguration()
    if group["expected_relation"] == "same_score_within_tolerance":
        return ScoreConfiguration(absolute_tolerance=parameters["absolute_tolerance"])
    labels: list[str] = judgment_spec["label_space"]
    return PreferenceConfiguration(
        first_label_index=labels.index(parameters["first_label"]),
        second_label_index=labels.index(parameters["second_label"]),
        tie_label_index=labels.index(parameters["tie_label"])
        if "tie_label" in parameters
        else None,
    )
