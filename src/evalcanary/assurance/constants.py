"""Closed vocabularies and bounded policy for assurance v1."""

from __future__ import annotations

INPUT_SCHEMA = "evaluator-assurance-input-v1"
CONTRACT_SCHEMA = "evaluator-assurance-contract-v1"
REPORT_SCHEMA = "evaluator-assurance-report-v1"
MANIFEST_ALGORITHM = "evaluator-assurance-manifest-v1"

RECORD_TYPES = frozenset(
    {
        "header",
        "critical_group",
        "invariance_group",
        "anchor_set",
        "case",
        "trial",
        "anchor",
    }
)
STATUSES = frozenset({"determinate", "abstain", "indeterminate", "error"})
PRESENCES = frozenset({"present", "missing", "intentionally_omitted", "not_applicable"})
ROLES = frozenset({"baseline", "candidate"})
SEVERITIES = frozenset({"hard", "review", "info"})
RULE_RESULTS = frozenset({"satisfied", "violated", "missing", "not_applicable"})

FIXED_EVALUATOR_COMPONENTS = frozenset(
    {"implementation", "rubric_prompt", "model_provider"}
)
FIXED_CONTEXT_COMPONENTS = frozenset(
    {
        "runner_adapter",
        "harness_configuration",
        "preprocessing",
        "runtime",
        "dependency_lock",
        "container_image",
        "sampling_settings",
        "response_order",
        "locale_time",
        "resource_policy",
        "task_benchmark",
    }
)
MOVABLE_COMPONENTS = frozenset({"parser", "aggregation_policy"})

PROVENANCE_FIELDS = frozenset(
    {
        "corpus_source",
        "corpus_version",
        "corpus_revision",
        "corpus_hash",
        "corpus_license",
        "evaluator_source",
        "implementation",
        "rubric_prompt",
        "configuration",
        "parser",
        "aggregation_policy",
        "model_provider",
        "model_version",
        "adapter",
        "runner",
        "tool_version",
        "dependency_lock",
        "container_image",
        "sampling_settings",
        "response_order",
        "locale_time",
        "resource_policy",
        "task_benchmark",
        "source_schema",
        "original_artifact_hash",
        "source_timestamp",
        "creation_timestamp",
        "redaction",
        "omission",
        "evidence_policy",
        "source_row",
        "source_judgment",
        "test_command_status",
        "reset_status",
        "source_url",
        "license_url",
    }
)

RELATIONS = frozenset(
    {"same_label", "swapped_preference", "same_score_within_tolerance"}
)
METRICS = frozenset(
    {
        "corpus_equal",
        "context_isolated",
        "determinate_coverage",
        "determinate_coverage_delta",
        "status_count",
        "new_status_count",
        "determinate_label_count",
        "determinate_label_transition_count",
        "critical_regression_count",
        "unstable_case_count",
        "invariance_violation_count",
        "invariance_not_evaluable_count",
        "anchor_coverage",
        "anchor_disagreement_count",
        "provenance_present",
        "score_delta",
    }
)
OPERATORS = frozenset({"eq", "ne", "lt", "lte", "gt", "gte"})
SCOPES = frozenset(
    {"all_cases", "critical_group", "invariance_group", "anchor_set", "provenance"}
)

LIMIT_DEFAULTS: dict[str, int] = {
    "total_input_bytes": 67_108_864,
    "line_bytes": 262_144,
    "total_records": 100_000,
    "cases": 10_000,
    "trials_per_case_evaluation": 32,
    "pairing_keys_per_case": 32,
    "critical_groups": 256,
    "critical_memberships_per_case": 64,
    "invariance_groups": 10_000,
    "invariance_members": 32,
    "invariance_memberships_per_case": 64,
    "anchor_sets": 32,
    "anchors_per_case_set": 64,
    "aggregation_inputs": 64,
    "general_string_scalars": 4_096,
    "general_string_bytes": 16_384,
    "map_keys": 128,
    "array_items": 1_024,
    "nesting_depth": 12,
    "extension_bytes": 65_536,
    "details_bytes": 32_768,
    "json_report_bytes": 67_108_864,
    "markdown_report_bytes": 33_554_432,
    "html_report_bytes": 50_331_648,
    "combined_report_bytes": 134_217_728,
}

LIMIT_CEILINGS: dict[str, int] = {
    "total_input_bytes": 268_435_456,
    "line_bytes": 1_048_576,
    "total_records": 400_000,
    "cases": 50_000,
    "trials_per_case_evaluation": 64,
    "pairing_keys_per_case": 64,
    "critical_groups": 1_024,
    "critical_memberships_per_case": 64,
    "invariance_groups": 50_000,
    "invariance_members": 128,
    "invariance_memberships_per_case": 64,
    "anchor_sets": 128,
    "anchors_per_case_set": 256,
    "aggregation_inputs": 256,
    "general_string_scalars": 16_384,
    "general_string_bytes": 65_536,
    "map_keys": 512,
    "array_items": 4_096,
    "nesting_depth": 16,
    "extension_bytes": 262_144,
    "details_bytes": 131_072,
    "json_report_bytes": 268_435_456,
    "markdown_report_bytes": 134_217_728,
    "html_report_bytes": 201_326_592,
    "combined_report_bytes": 536_870_912,
}

NON_OVERRIDABLE_LIMITS = frozenset(
    {
        "critical_memberships_per_case",
        "invariance_memberships_per_case",
        "nesting_depth",
    }
)

LIMITATIONS = (
    "The report describes only the supplied frozen evidence and does not establish evaluator correctness, fairness, lack of bias, certification, or safety.",
    "Isolation is relative to the supplied complete component inventory and is not causal identification.",
    "Repeated-trial diagnostics are descriptive; no independence, population, confidence, significance, ranking, or causal claim is made.",
    "Human annotations are optional anchors, not universal ground truth, and multiple annotations are not independent cases.",
    "Cryptographic hashes aid byte identity and replay; they do not prove semantic equivalence or confidentiality and may reveal low-entropy known content.",
)
