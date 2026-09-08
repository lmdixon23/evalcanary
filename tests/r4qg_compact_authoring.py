"""Project-formatted U/U2/V authoring surface used by the R4Q-G line gate."""

import csv
from decimal import Decimal

from evalcanary import assurance as a

SOURCE_ERROR = {"error_class": "SourceReportedError"}
CANDIDATE = {"role": "candidate"}
CANDIDATE_LABEL = {"role": "candidate", "dimension": "label"}
CANDIDATE_SCORE = {"role": "candidate", "dimension": "score"}
HARD_ALL = ("hard", "all_cases", None)
REVIEW_ALL = ("review", "all_cases", None)
EQ_HARD = ("eq", Decimal("0"), "hard_fail")
EQ_REVIEW = ("eq", Decimal("0"), "review")
NEW_ERRORS = ("new_status_count", {"status": "error"}, "Reject new errors.")
INV_VIOLATION = ("invariance_violation_count", CANDIDATE, "Review violations.")
INV_MISSING = ("invariance_not_evaluable_count", CANDIDATE, "Review missing evidence.")
LABEL_UNSTABLE = ("unstable_case_count", CANDIDATE_LABEL, "Review label instability.")
SCORE_UNSTABLE = ("unstable_case_count", CANDIDATE_SCORE, "Review score instability.")


def provenance(dataset: str, task: str, evaluator: str) -> dict[str, object]:
    return {
        "corpus_source": a.component_value("present", identity=dataset),
        "task_benchmark": a.component_value("present", identity=task),
        "evaluator_source": a.component_value("present", identity=evaluator),
    }


def evaluation_pair(evaluator, context, ownership, source):
    evaluator_id, versions, parsers, aggregations = evaluator
    context_id, context_fingerprint = context
    dataset, task = source
    return [
        a.complete_evaluation(
            evaluation_id=f"{evaluator_id}-{version}-{role}",
            role=role,
            evaluator_id=evaluator_id,
            evaluator_version=version,
            evaluator_fingerprint_sha256=a.sha256_bytes(
                f"{evaluator_id}@{version}".encode()
            ),
            context_id=context_id,
            context_fingerprint_sha256=context_fingerprint,
            component_ownership=ownership,
            component_values={
                "implementation": a.component_value(
                    "present", identity="local deterministic ruleset"
                ),
                "parser": a.component_value("present", identity=parser),
                "aggregation_policy": a.component_value(
                    "present", identity=aggregation
                ),
            },
            confirm_unlisted_not_applicable=True,
            provenance=provenance(dataset, task, evaluator_id),
        )
        for role, version, parser, aggregation in zip(
            ("baseline", "candidate"), versions, parsers, aggregations, strict=True
        )
    ]


def add_rows(packet, rows_path, critical, invariance):
    with rows_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for case_id in sorted({row["case_id"] for row in rows}):
        packet.add_case(
            case_id,
            critical_group_ids=critical.get(case_id, []),
            invariance_group_ids=invariance.get(case_id, []),
            display_label=case_id,
        )
    evaluation_ids = packet.evaluation_ids_by_role
    orders: dict[tuple[str, str], int] = {}
    for row in rows:
        key = (row["case_id"], row["role"])
        order = orders.get(key, 0)
        orders[key] = order + 1
        determinate = row["status"] == "determinate"
        score = Decimal(row["score"]) if determinate and row["score"] else None
        error = SOURCE_ERROR if row["status"] == "error" else None
        packet.add_trial(
            case_id=row["case_id"],
            evaluation_id=evaluation_ids[row["role"]],
            trial_id=f"{row['case_id']}-{row['role']}-{row['trial_key']}",
            source_order=order,
            pairing_key=row["trial_key"],
            status=row["status"],
            label=row["label"] if determinate else None,
            score=score,
            error=error,
        )


def rules(specifications):
    result = []
    for rule_id, applicability, measure, decision in specifications:
        result.append(
            a.Rule(
                rule_id=rule_id,
                severity=applicability[0],
                scope=applicability[1],
                scope_id=applicability[2],
                metric=measure[0],
                parameters=measure[1],
                operator=decision[0],
                threshold=decision[1],
                missing_evidence=decision[2],
                rationale=measure[2],
            )
        )
    return result


def build_u(rows_path, candidate_version):
    ownership = {"parser": "evaluator", "aggregation_policy": "evaluator"}
    versions = ("1.0", candidate_version)
    parsers = ("route-parser@1.0", "route-parser@2.0")
    aggregations = ("route-aggregation@1.0", "route-aggregation@2.0")
    evaluator = ("route-judge", versions, parsers, aggregations)
    context_hash = a.sha256_value({"dataset": "fresh-u", "task": "routing"})
    context = ("fresh-u:routing", context_hash)
    packet = a.AssurancePacket(
        artifact_id=f"fresh-u-{candidate_version}-migration",
        corpus_id="fresh-u-corpus",
        identity_level="case_ids",
        judgment_spec={
            "judgment_spec_id": "fresh-u-pass-fail",
            "kind": "categorical",
            "label_space": ["pass", "fail"],
            "score_spec": None,
            "repeat_score_tolerance": None,
        },
        evaluations=evaluation_pair(
            evaluator, context, ownership, ("fresh-u", "routing")
        ),
        component_ownership=ownership,
        provenance=provenance("fresh-u", "routing", "route-judge"),
        allowed_context_differences=[],
    )
    add_rows(
        packet,
        rows_path,
        critical={"u-route": ["u-release-blockers"]},
        invariance={"u-route": ["u-paraphrase"], "u-steady": ["u-paraphrase"]},
    )
    packet.add_critical_group(
        "u-release-blockers",
        title="U release blockers",
        declaration_source="supplied Fresh U migration brief",
        rationale="routing decisions that block a release",
    ).add_invariance_group(
        "u-paraphrase",
        member_case_ids=["u-route", "u-steady"],
        transformation_id="u-paraphrase",
        transformation_version="1",
        expected_relation="same_label",
        relation_parameters={},
        severity="review",
        declaration_source="supplied Fresh U migration brief",
        rationale="supplied paraphrase invariance relation",
    ).add_anchor_set(
        "u-human-labels",
        label_space=["pass", "fail"],
        protocol_id="human-review-v1",
        protocol_version="1",
        aggregation_method="none",
        clustering_unit="case",
        source_revision="human-review-v1",
        source_sha256=a.sha256_bytes(b"human-review-v1"),
        license="not supplied",
        provenance={},
    ).add_anchor(
        "u-route-human-v1",
        anchor_set_id="u-human-labels",
        case_id="u-route",
        cluster_id="u-route",
        annotation_id="u-route-human-v1",
        annotator_id=None,
        kind="raw_annotation",
        status="determinate",
        label="pass",
        reason=None,
        aggregation_inputs=[],
        adjudication_rationale=None,
        provenance={},
    )
    critical = ("hard", "critical_group", "u-release-blockers")
    regression = (
        "critical_regression_count",
        {"from_label": "pass", "to_label": "fail"},
        "Reject critical pass-to-fail changes.",
    )
    invariant = ("review", "invariance_group", "u-paraphrase")
    policy = rules(
        [
            ("u-new-errors", HARD_ALL, NEW_ERRORS, EQ_HARD),
            ("u-critical-regression", critical, regression, EQ_HARD),
            ("u-invariance-violation", invariant, INV_VIOLATION, EQ_REVIEW),
            ("u-invariance-not-evaluable", invariant, INV_MISSING, EQ_REVIEW),
        ]
    )
    return packet, a.Contract("fresh-u-policy", "1", policy)


def build_v(rows_path):
    ownership = {"parser": "evaluator", "aggregation_policy": "context"}
    versions = ("3.0", "4.0")
    parsers = ("quality-parser@3.0", "quality-parser@4.0")
    aggregations = ("repeat-mean-policy@1", "repeat-mean-policy@1")
    evaluator = ("quality-judge", versions, parsers, aggregations)
    context_hash = a.sha256_value(
        {
            "dataset": "fresh-v",
            "task": "quality",
            "aggregation": "repeat-mean-policy@1",
        }
    )
    context = ("fresh-v:quality", context_hash)
    packet = a.AssurancePacket(
        artifact_id="fresh-v-4.0-migration",
        corpus_id="fresh-v-corpus",
        identity_level="case_ids",
        judgment_spec={
            "judgment_spec_id": "fresh-v-pass-fail-unit-interval",
            "kind": "categorical_and_numeric",
            "label_space": ["pass", "fail"],
            "score_spec": {
                "scale_id": "unit-interval",
                "domain_min": Decimal("0"),
                "domain_max": Decimal("1"),
                "direction": "higher_is_better",
                "comparison": "delta",
                "valid_statuses": ["determinate"],
                "threshold_relationship": None,
            },
            "repeat_score_tolerance": Decimal("0.05"),
        },
        evaluations=evaluation_pair(
            evaluator, context, ownership, ("fresh-v", "quality")
        ),
        component_ownership=ownership,
        provenance=provenance("fresh-v", "quality", "quality-judge"),
        allowed_context_differences=[],
    )
    add_rows(
        packet,
        rows_path,
        critical={},
        invariance={
            "v-rel-a": ["v-calibration-pair"],
            "v-rel-b": ["v-calibration-pair"],
        },
    )
    packet.add_invariance_group(
        "v-calibration-pair",
        member_case_ids=["v-rel-a", "v-rel-b"],
        transformation_id="v-calibration-pair",
        transformation_version="1",
        expected_relation="same_score_within_tolerance",
        relation_parameters={"absolute_tolerance": Decimal("0.05")},
        severity="review",
        declaration_source="supplied Fresh V migration brief",
        rationale="supplied calibration relation",
    )
    invariant = ("review", "invariance_group", "v-calibration-pair")
    score_delta = ("score_delta", {}, "Reject mean paired score delta below -0.05.")
    policy = rules(
        [
            ("v-new-errors", HARD_ALL, NEW_ERRORS, EQ_HARD),
            ("v-label-instability", REVIEW_ALL, LABEL_UNSTABLE, EQ_REVIEW),
            ("v-score-instability", REVIEW_ALL, SCORE_UNSTABLE, EQ_REVIEW),
            ("v-invariance-violation", invariant, INV_VIOLATION, EQ_REVIEW),
            ("v-invariance-not-evaluable", invariant, INV_MISSING, EQ_REVIEW),
            (
                "v-mean-score-delta",
                HARD_ALL,
                score_delta,
                ("gte", Decimal("-0.05"), "hard_fail"),
            ),
        ]
    )
    return packet, a.Contract("fresh-v-policy", "1", policy)


def write_scenario(scenario, rows_path, output):
    if scenario == "V":
        packet, contract = build_v(rows_path)
    elif scenario in {"U", "U2"}:
        packet, contract = build_u(rows_path, {"U": "2.0", "U2": "2.1"}[scenario])
    else:
        raise ValueError("scenario must be U, U2, or V")
    output.mkdir(parents=True, exist_ok=False)
    input_path = packet.write(output / "evaluator-assurance.jsonl")
    contract.write(output / "evaluator-contract.json", artifact=input_path)
