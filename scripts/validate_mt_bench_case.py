#!/usr/bin/env python3
"""Validate and materialize the pinned local-only MT-Bench Case C packet."""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import importlib
import json
import sys
import zipfile
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Any

from evalcanary.assurance.engine import build_report, exit_code_for_report
from evalcanary.assurance.numeric import canonical_json_text
from evalcanary.assurance.renderers import write_report_bundle
from evalcanary.assurance.schema import Limits, load_artifact, load_contract

_SCRIPT_DIRECTORY = Path(__file__).resolve().parent
if str(_SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIRECTORY))

from prepare_assurance_cases import (  # noqa: E402
    _write_json,
    build_case_c_artifact,
    build_case_c_contract,
    case_c_group_id,
    case_c_group_key,
    normalize_case_c_human_winner,
    normalize_case_c_winner,
)

_PARQUET_COLUMNS = (
    "question_id",
    "turn",
    "model_a",
    "model_b",
    "winner",
    "judge",
)
_AGGREGATE_WINNERS = frozenset({"model_a", "model_b", "tie", "tie (inconsistent)"})
_HUMAN_WINNERS = frozenset({"model_a", "model_b", "tie"})
_RAW_WINNERS = frozenset({"model_1", "model_2", "tie", "error"})


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_case_lock(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Case lock must be one JSON object.")
    return value


def _verify_source_files(source_root: Path, case_lock: dict[str, Any]) -> list[str]:
    verified: list[str] = []
    for relative, expected in sorted(case_lock["source_files"].items()):
        path = source_root / relative
        if not path.is_file() or _sha256(path) != expected:
            raise ValueError(f"Pinned source identity mismatch: {relative}")
        verified.append(relative)
    return verified


def _verify_pair_semantics(
    semantics_root: Path, case_lock: dict[str, Any]
) -> list[str]:
    verified: list[str] = []
    texts: dict[str, str] = {}
    for relative, expected in sorted(
        case_lock["pair_semantics"]["source_files"].items()
    ):
        path = semantics_root / relative
        if not path.is_file() or _sha256(path) != expected:
            raise ValueError(f"Pinned pair-semantics identity mismatch: {relative}")
        verified.append(relative)
        texts[relative] = path.read_text(encoding="utf-8")
    common = texts["fastchat-587d5cf-common.py"]
    required = (
        "question, answer_1, answer_2, judge, ref_answer",
        "question, answer_2, answer_1, judge, ref_answer",
        'g1_map = {"A": "model_1", "B": "model_2"}',
        'g2_map = {"A": "model_2", "B": "model_1"}',
        'winner = "inconsistent"',
    )
    if any(signature not in common for signature in required):
        raise ValueError("Pinned FastChat pair-semantics signature mismatch.")
    return verified


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Pinned raw JSONL contains a duplicate object key.")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"Pinned raw JSONL contains a non-finite number: {value}")


def _verify_raw_identity(path: Path, raw_lock: dict[str, Any]) -> None:
    if not path.is_file() or path.stat().st_size != raw_lock["bytes"]:
        raise ValueError("Pinned raw source byte-length mismatch.")
    if _sha256(path) != raw_lock["sha256"]:
        raise ValueError("Pinned raw source SHA-256 mismatch.")


def _verify_decoder_install(decoder_path: Path, decoder_wheel: Path) -> int:
    """Verify every hashed wheel member before importing the native decoder."""

    with zipfile.ZipFile(decoder_wheel) as archive:
        record_names = [
            name for name in archive.namelist() if name.endswith(".dist-info/RECORD")
        ]
        if len(record_names) != 1:
            raise ValueError("Fixture decoder wheel RECORD inventory mismatch.")
        record_text = archive.read(record_names[0]).decode("utf-8")
    verified = 0
    for relative, encoded_hash, encoded_size in csv.reader(record_text.splitlines()):
        if not encoded_hash:
            continue
        if "\\" in relative or relative.startswith("/") or ".." in relative.split("/"):
            raise ValueError("Fixture decoder wheel contains an unsafe member path.")
        algorithm, separator, expected_hash = encoded_hash.partition("=")
        if separator != "=" or algorithm != "sha256":
            raise ValueError("Fixture decoder wheel uses an unsupported RECORD hash.")
        target = decoder_path.joinpath(*relative.split("/"))
        if not target.is_file() or target.is_symlink():
            raise ValueError(f"Fixture decoder install is incomplete: {relative}")
        if encoded_size and target.stat().st_size != int(encoded_size):
            raise ValueError(f"Fixture decoder install size mismatch: {relative}")
        observed_hash = base64.urlsafe_b64encode(bytes.fromhex(_sha256(target))).rstrip(
            b"="
        )
        if observed_hash.decode("ascii") != expected_hash:
            raise ValueError(f"Fixture decoder install hash mismatch: {relative}")
        verified += 1
    if verified == 0:
        raise ValueError("Fixture decoder wheel RECORD has no verified members.")
    for shadow_name in ("pyarrow.py", "pyarrow.pyc", "pyarrow.pyd"):
        if (decoder_path / shadow_name).exists():
            raise ValueError("Fixture decoder path contains an import shadow.")
    return verified


def _validate_raw_record(
    record: Any, position: int, required_fields: set[str]
) -> dict[str, Any]:
    if not isinstance(record, dict) or set(record) != required_fields:
        raise ValueError(f"Pinned raw source schema mismatch at row {position}.")
    for name in ("question_id", "turn"):
        if type(record[name]) is not int:
            raise ValueError(f"Pinned raw source type mismatch at row {position}.")
    if record["turn"] not in {1, 2}:
        raise ValueError(f"Pinned raw source turn mismatch at row {position}.")
    for name in (
        "model_1",
        "model_2",
        "g1_winner",
        "g2_winner",
        "g1_user_prompt",
        "g2_user_prompt",
        "g1_judgment",
        "g2_judgment",
    ):
        if not isinstance(record[name], str):
            raise ValueError(f"Pinned raw source type mismatch at row {position}.")
    if not record["model_1"] or not record["model_2"]:
        raise ValueError(
            f"Pinned raw source model identity is empty at row {position}."
        )
    if record["model_1"] == record["model_2"]:
        raise ValueError(f"Pinned raw source repeats one model at row {position}.")
    if record["g1_winner"] not in _RAW_WINNERS:
        raise ValueError(f"Pinned raw game-1 winner mismatch at row {position}.")
    if record["g2_winner"] not in _RAW_WINNERS:
        raise ValueError(f"Pinned raw game-2 winner mismatch at row {position}.")
    judge = record["judge"]
    if (
        not isinstance(judge, list)
        or len(judge) != 2
        or any(not isinstance(item, str) or not item for item in judge)
    ):
        raise ValueError(f"Pinned raw judge identity mismatch at row {position}.")
    timestamp = record["tstamp"]
    if type(timestamp) is not int and not isinstance(timestamp, Decimal):
        raise ValueError(f"Pinned raw timestamp type mismatch at row {position}.")
    if isinstance(timestamp, Decimal) and not timestamp.is_finite():
        raise ValueError(f"Pinned raw timestamp is non-finite at row {position}.")
    return {
        "source_position": position,
        "question_id": record["question_id"],
        "turn": record["turn"],
        "model_1": record["model_1"],
        "model_2": record["model_2"],
        "g1_winner": record["g1_winner"],
        "g2_winner": record["g2_winner"],
        "judge": list(judge),
    }


def _load_raw_rows(
    path: Path, raw_lock: dict[str, Any]
) -> tuple[list[dict[str, Any]], int]:
    _verify_raw_identity(path, raw_lock)
    required_fields = set(raw_lock["required_fields"])
    rows: list[dict[str, Any]] = []
    observed_max = 0
    with path.open("rb") as stream:
        for position, line in enumerate(stream):
            observed_max = max(observed_max, len(line))
            if not line or len(line) > raw_lock["max_record_bytes"]:
                raise ValueError(f"Pinned raw record-size mismatch at row {position}.")
            try:
                record = json.loads(
                    line.decode("utf-8"),
                    parse_float=Decimal,
                    parse_int=int,
                    parse_constant=_reject_constant,
                    object_pairs_hook=_reject_duplicates,
                )
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ValueError(
                    f"Pinned raw JSONL decode failure at row {position}."
                ) from error
            rows.append(_validate_raw_record(record, position, required_fields))
    if len(rows) != raw_lock["records"]:
        raise ValueError("Pinned raw source record-count mismatch.")
    return rows, observed_max


def _validate_parquet_row(
    row: dict[str, Any], *, human: bool, position: int
) -> dict[str, Any]:
    for name in ("question_id", "turn"):
        if type(row[name]) is not int:
            raise ValueError(f"Pinned parquet type mismatch at row {position}.")
    if row["turn"] not in {1, 2}:
        raise ValueError(f"Pinned parquet turn mismatch at row {position}.")
    for name in ("model_a", "model_b", "winner", "judge"):
        if not isinstance(row[name], str) or not row[name]:
            raise ValueError(f"Pinned parquet type mismatch at row {position}.")
    if row["model_a"] == row["model_b"]:
        raise ValueError(f"Pinned parquet repeats one model at row {position}.")
    vocabulary = _HUMAN_WINNERS if human else _AGGREGATE_WINNERS
    if row["winner"] not in vocabulary:
        raise ValueError(f"Pinned parquet winner mismatch at row {position}.")
    return {**row, "source_position": position}


def _load_parquets(
    source_root: Path,
    case_lock: dict[str, Any],
    decoder_path: Path,
    decoder_wheel: Path,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any], int]:
    decoder = case_lock["decoder"]
    if (
        decoder_wheel.name != decoder["wheel"]
        or _sha256(decoder_wheel) != decoder["wheel_sha256"]
    ):
        raise ValueError("Fixture decoder wheel identity mismatch.")
    verified_decoder_files = _verify_decoder_install(decoder_path, decoder_wheel)
    sys.path.insert(0, str(decoder_path.resolve()))
    pyarrow = importlib.import_module("pyarrow")
    parquet = importlib.import_module("pyarrow.parquet")
    if pyarrow.__version__ != decoder["version"]:
        raise ValueError("Fixture decoder version mismatch.")
    expected_module = (decoder_path / "pyarrow" / "__init__.py").resolve()
    module_file = pyarrow.__file__
    if (
        not isinstance(module_file, str)
        or Path(module_file).resolve() != expected_module
    ):
        raise ValueError("Fixture decoder resolved outside its verified package.")
    rows_by_name: dict[str, list[dict[str, Any]]] = {}
    artifacts: dict[str, Any] = {}
    for name in ("gpt4_pair.parquet", "human.parquet"):
        path = source_root / "case-c" / name
        parquet_file = parquet.ParquetFile(path)
        available = set(parquet_file.schema_arrow.names)
        if not set(_PARQUET_COLUMNS) <= available:
            raise ValueError(f"Pinned parquet lacks required source fields: {name}")
        if parquet_file.metadata.num_rows != case_lock["expected_rows"][name]:
            raise ValueError(f"Pinned parquet row-count mismatch: {name}")
        decoded = parquet.read_table(path, columns=list(_PARQUET_COLUMNS)).to_pylist()
        human = name == "human.parquet"
        rows = [
            _validate_parquet_row(row, human=human, position=position)
            for position, row in enumerate(decoded)
        ]
        rows_by_name[name] = rows
        artifacts[name] = {
            "sha256": case_lock["source_files"][f"case-c/{name}"],
            "rows": len(rows),
            "winner_counts": dict(
                sorted(Counter(str(row["winner"]) for row in rows).items())
            ),
        }
    return rows_by_name, artifacts, verified_decoder_files


def analyze_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Analyze order coverage in aggregate-format rows for synthetic tests."""

    ordered = Counter(
        (row["question_id"], row["turn"], row["model_a"], row["model_b"])
        for row in rows
    )
    unordered = Counter(
        (
            row["question_id"],
            row["turn"],
            tuple(sorted((row["model_a"], row["model_b"]))),
        )
        for row in rows
    )
    rows_with_reverse = sum(
        (row["question_id"], row["turn"], row["model_b"], row["model_a"]) in ordered
        for row in rows
    )
    winners = Counter(str(row["winner"]) for row in rows)
    return {
        "rows": len(rows),
        "ordered_unique": len(ordered),
        "ordered_duplicate_keys": sum(count > 1 for count in ordered.values()),
        "unordered_group_sizes": {
            str(size): count
            for size, count in sorted(Counter(unordered.values()).items())
        },
        "rows_with_reverse_order": rows_with_reverse,
        "eligible_two_order_groups": sum(size == 2 for size in unordered.values()),
        "winner_counts": dict(sorted(winners.items())),
        "unsupported_winner_counts": {
            winner: count
            for winner, count in sorted(winners.items())
            if winner not in {"model_a", "model_b", "tie"}
        },
        "judge_count": len({str(row["judge"]) for row in rows}),
    }


def _model_relative_winner(row: dict[str, Any], game: int) -> str | None:
    winner = str(row[f"g{game}_winner"])
    if winner in {"tie", "error"}:
        return winner
    if winner not in {"model_1", "model_2"}:
        return None
    return str(row[winner])


def _two_game_identity(row: dict[str, Any]) -> tuple[str | None, str | None]:
    return (_model_relative_winner(row, 1), _model_relative_winner(row, 2))


def _normalized_two_game_outcomes(
    row: dict[str, Any],
) -> tuple[tuple[str, str | None], tuple[str, str | None]]:
    game_1 = normalize_case_c_winner(str(row["g1_winner"]), 1)
    game_2 = normalize_case_c_winner(str(row["g2_winner"]), 2)
    if str(row["model_1"]) < str(row["model_2"]):
        return game_1, game_2
    return game_2, game_1


def _aggregate_from_raw(
    row: dict[str, Any], aggregate_row: dict[str, Any] | None = None
) -> str:
    """Reproduce the pinned FastChat two-game aggregate winner semantics."""

    first, second = _two_game_identity(row)
    if first != second:
        return "tie (inconsistent)"
    if first in {"tie", "error"}:
        return str(first)
    model_a, model_b = (
        (str(aggregate_row["model_a"]), str(aggregate_row["model_b"]))
        if aggregate_row is not None
        else tuple(sorted((str(row["model_1"]), str(row["model_2"]))))
    )
    if first == model_a:
        return "model_a"
    if first == model_b:
        return "model_b"
    raise ValueError("Raw winner does not identify either source model.")


def _candidate_invariance(row: dict[str, Any]) -> str:
    first = normalize_case_c_winner(str(row["g1_winner"]), 1)
    second = normalize_case_c_winner(str(row["g2_winner"]), 2)
    if first[0] != "determinate" or second[0] != "determinate":
        return "not_evaluable"
    if (first[1], second[1]) in {("a", "b"), ("b", "a"), ("tie", "tie")}:
        return "satisfied"
    return "violated"


def _select_raw_groups(
    raw_rows: list[dict[str, Any]],
    case_lock: dict[str, Any],
    eligible_keys: set[tuple[int, int, tuple[str, str]]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    candidates: dict[tuple[int, int, tuple[str, str]], list[dict[str, Any]]] = (
        defaultdict(list)
    )
    for row in raw_rows:
        key = case_c_group_key(row)
        if key in eligible_keys:
            candidates[key].append(row)
    if set(candidates) != eligible_keys:
        raise ValueError("Raw source does not cover every aggregate group key.")
    selected: list[dict[str, Any]] = []
    selection_evidence: list[dict[str, Any]] = []
    changed_outcome = 0
    changed_aggregate = 0
    duplicate_rows = 0
    for rows in candidates.values():
        ordered = sorted(rows, key=lambda row: int(row["source_position"]))
        first = ordered[0]
        selected.append(first)
        duplicate_rows += len(ordered) - 1
        for later in ordered[1:]:
            changed_outcome += _normalized_two_game_outcomes(
                later
            ) != _normalized_two_game_outcomes(first)
            changed_aggregate += _aggregate_from_raw(later) != _aggregate_from_raw(
                first
            )
        normalized_games = {
            f"game_{game}": {
                "source_winner": str(first[f"g{game}_winner"]),
                "status": normalize_case_c_winner(str(first[f"g{game}_winner"]), game)[
                    0
                ],
                "display_label": normalize_case_c_winner(
                    str(first[f"g{game}_winner"]), game
                )[1],
            }
            for game in (1, 2)
        }
        selection_evidence.append(
            {
                "group_id": case_c_group_id(case_lock, first),
                "candidate_source_positions": [
                    int(row["source_position"]) for row in ordered
                ],
                "selected_source_position": int(first["source_position"]),
                "rejected_source_positions": [
                    int(row["source_position"]) for row in ordered[1:]
                ],
                "duplicate_count": len(ordered) - 1,
                "selected_game_outcomes": normalized_games,
            }
        )
    selected.sort(key=lambda row: int(row["source_position"]))
    selection_evidence.sort(key=lambda row: int(row["selected_source_position"]))
    return selected, {
        "raw_unordered_groups": len(candidates),
        "raw_rows_outside_aggregate_scope": len(raw_rows)
        - sum(len(rows) for rows in candidates.values()),
        "later_duplicate_rows": duplicate_rows,
        "later_duplicate_outcome_changes": changed_outcome,
        "later_duplicate_aggregate_changes": changed_aggregate,
        "selection_policy": "lowest_raw_source_position_per_aggregate_key",
        "selection_evidence": selection_evidence,
    }


def _human_diagnostics(
    case_lock: dict[str, Any],
    selected_rows: list[dict[str, Any]],
    human_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    selected = {case_c_group_key(row): row for row in selected_rows}
    ordered_cases: set[tuple[tuple[int, int, tuple[str, str]], int]] = set()
    games_by_group: dict[tuple[int, int, tuple[str, str]], set[int]] = defaultdict(set)
    agreements = 0
    disagreements = 0
    source_errors = 0
    confusion: Counter[str] = Counter()
    attachment_counts: Counter[str] = Counter()
    for human in human_rows:
        human_models = sorted((str(human["model_a"]), str(human["model_b"])))
        key = (
            int(human["question_id"]),
            int(human["turn"]),
            (human_models[0], human_models[1]),
        )
        raw = selected.get(key)
        if raw is None:
            raise ValueError("Human row does not map to one selected raw group.")
        human_order = (str(human["model_a"]), str(human["model_b"]))
        raw_order = (str(raw["model_1"]), str(raw["model_2"]))
        if human_order == raw_order:
            game = 1
        elif human_order == tuple(reversed(raw_order)):
            game = 2
        else:
            raise ValueError("Human row does not map to exactly one actual game order.")
        attachment_counts[f"game_{game}"] += 1
        ordered_cases.add((key, game))
        games_by_group[key].add(game)
        source_status, source_label = normalize_case_c_winner(
            str(raw[f"g{game}_winner"]), game
        )
        human_label = normalize_case_c_human_winner(str(human["winner"]))
        source_key = source_label if source_status == "determinate" else "error"
        confusion[f"{human_label}->{source_key}"] += 1
        if source_status == "determinate" and source_label == human_label:
            agreements += 1
        else:
            disagreements += 1
        source_errors += source_status == "error"
    game_shapes = Counter(
        "both_games"
        if games == {1, 2}
        else "game_1_only"
        if games == {1}
        else "game_2_only"
        for games in games_by_group.values()
    )
    total_groups = len(selected_rows)
    anchored_groups = len(games_by_group)
    return {
        "annotations": len(human_rows),
        "game_1": attachment_counts["game_1"],
        "game_2": attachment_counts["game_2"],
        "anchored_ordered_cases": len(ordered_cases),
        "missing_ordered_cases": total_groups * 2 - len(ordered_cases),
        "anchored_groups": anchored_groups,
        "missing_groups": total_groups - anchored_groups,
        "game_1_only_groups": game_shapes["game_1_only"],
        "game_2_only_groups": game_shapes["game_2_only"],
        "both_games_groups": game_shapes["both_games"],
        "neither_game_groups": total_groups - anchored_groups,
        "compatible_agreements": agreements,
        "compatible_disagreements": disagreements,
        "source_error_annotations": source_errors,
        "compatible_label_confusion": dict(sorted(confusion.items())),
        "aggregation_method": "none",
        "clustering_unit": "revision-question-turn-unordered-model-pair",
        "source_revision": case_lock["revision"],
    }


def _report_invariance_counts(report: dict[str, Any], role: str) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for group in report["invariance_groups"]:
        instances = group["roles"][role]
        if len(instances) != 1:
            raise ValueError(
                "Case C invariance group did not emit one result per role."
            )
        counts[str(instances[0]["result"])] += 1
    return {name: counts[name] for name in ("satisfied", "violated", "not_evaluable")}


def _expect_equal(label: str, observed: Any, expected: Any) -> None:
    if observed != expected:
        raise ValueError(f"{label} mismatch: expected {expected!r}, got {observed!r}")


def _materialize_packet(
    output_root: Path,
    case_lock: dict[str, Any],
    selected_rows: list[dict[str, Any]],
    human_rows: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, str]]:
    packet_root = output_root / "packet"
    input_path = packet_root / "input.jsonl"
    contract_path = packet_root / "contract.json"
    report_root = packet_root / "report"
    baseline_errors = sum(row["g1_winner"] == "error" for row in selected_rows)
    candidate_errors = sum(
        row[f"g{game}_winner"] == "error" for row in selected_rows for game in (1, 2)
    )
    candidate_not_evaluable = sum(
        _candidate_invariance(row) == "not_evaluable" for row in selected_rows
    )
    records = build_case_c_artifact(case_lock, selected_rows, human_rows)
    contract = build_case_c_contract(
        group_count=len(selected_rows),
        baseline_error_count=baseline_errors,
        candidate_error_count=candidate_errors,
        candidate_not_evaluable_count=candidate_not_evaluable,
    )
    _write_json(input_path, records, jsonl=True)
    _write_json(contract_path, contract)
    artifact = load_artifact(input_path)
    loaded_contract = load_contract(contract_path, artifact)
    report = build_report(artifact, loaded_contract)
    write_report_bundle(
        report,
        report_root,
        limits=Limits(),
        source_paths=(input_path, contract_path),
    )
    if exit_code_for_report(report) != 0:
        raise ValueError("Materialized Case C report did not pass its contract.")
    paths = {
        "input": str(input_path),
        "contract": str(contract_path),
        "report_json": str(report_root / "report.json"),
        "report_markdown": str(report_root / "report.md"),
        "report_html": str(report_root / "report.html"),
    }
    hashes = {name: _sha256(Path(path)) for name, path in paths.items()}
    return report, {
        **paths,
        **{f"{name}_sha256": value for name, value in hashes.items()},
    }


def validate(
    *,
    source_root: Path,
    raw_source: Path,
    semantics_root: Path,
    decoder_path: Path,
    decoder_wheel: Path,
    case_lock_path: Path,
    output_root: Path,
) -> dict[str, Any]:
    locks = _load_case_lock(case_lock_path)
    case_lock = locks["case_c"]
    if (
        case_lock["publication_status"]
        != "BLOCKED_PENDING_SOURCE_LICENSE_CLARIFICATION"
    ):
        raise ValueError("Case C publication status is not fail-closed.")
    verified_parquets = _verify_source_files(source_root, case_lock)
    verified_semantics = _verify_pair_semantics(semantics_root, case_lock)
    raw_rows, observed_max_record_bytes = _load_raw_rows(
        raw_source, case_lock["raw_source"]
    )
    parquet_rows, parquet_artifacts, verified_decoder_files = _load_parquets(
        source_root, case_lock, decoder_path, decoder_wheel
    )
    aggregate_rows = parquet_rows["gpt4_pair.parquet"]
    eligible_keys: set[tuple[int, int, tuple[str, str]]] = set()
    for aggregate in aggregate_rows:
        aggregate_models = sorted(
            (str(aggregate["model_a"]), str(aggregate["model_b"]))
        )
        eligible_keys.add(
            (
                int(aggregate["question_id"]),
                int(aggregate["turn"]),
                (aggregate_models[0], aggregate_models[1]),
            )
        )
    _expect_equal(
        "aggregate unique group keys", len(eligible_keys), len(aggregate_rows)
    )
    selected_rows, selection = _select_raw_groups(raw_rows, case_lock, eligible_keys)
    expected = case_lock["expected_results"]
    _expect_equal(
        "selected group count", len(selected_rows), expected["selected_groups"]
    )
    selected_positions = [int(row["source_position"]) for row in selected_rows]
    _expect_equal(
        "first selected source position",
        selected_positions[0],
        expected["selected_source_position_first"],
    )
    _expect_equal(
        "last selected source position",
        selected_positions[-1],
        expected["selected_source_position_last"],
    )
    _expect_equal(
        "selected source position continuity",
        selected_positions,
        list(range(expected["selected_groups"])),
    )
    models = sorted(
        {str(row[name]) for row in selected_rows for name in ("model_1", "model_2")}
    )
    model_pairs = {case_c_group_key(row)[2] for row in selected_rows}
    question_ids = sorted({int(row["question_id"]) for row in selected_rows})
    coverage = {
        "models": models,
        "unordered_model_pairs": len(model_pairs),
        "question_ids": len(question_ids),
        "question_id_first": question_ids[0],
        "question_id_last": question_ids[-1],
        "groups_by_turn": {
            str(turn): count
            for turn, count in sorted(
                Counter(int(row["turn"]) for row in selected_rows).items()
            )
        },
    }
    _expect_equal("selected coverage", coverage, expected["coverage"])
    for name in (
        "later_duplicates",
        "later_duplicate_outcome_changes",
        "later_duplicate_aggregate_changes",
    ):
        observed_name = "later_duplicate_rows" if name == "later_duplicates" else name
        _expect_equal(name, selection[observed_name], expected[name])

    aggregate_by_key: dict[tuple[int, int, tuple[str, str]], dict[str, Any]] = {}
    for aggregate in aggregate_rows:
        aggregate_models = sorted(
            (str(aggregate["model_a"]), str(aggregate["model_b"]))
        )
        key = (
            int(aggregate["question_id"]),
            int(aggregate["turn"]),
            (aggregate_models[0], aggregate_models[1]),
        )
        if key in aggregate_by_key:
            raise ValueError("Aggregate parquet contains a duplicate group key.")
        aggregate_by_key[key] = aggregate
    selected_keys = {case_c_group_key(row) for row in selected_rows}
    _expect_equal("aggregate key coverage", set(aggregate_by_key), selected_keys)
    aggregate_mismatches = 0
    for row in selected_rows:
        aggregate = aggregate_by_key[case_c_group_key(row)]
        if {aggregate["model_a"], aggregate["model_b"]} != {
            row["model_1"],
            row["model_2"],
        }:
            raise ValueError("Aggregate model identities differ from raw source.")
        aggregate_mismatches += (
            _aggregate_from_raw(row, aggregate) != aggregate["winner"]
        )
    _expect_equal("aggregate crosscheck mismatch count", aggregate_mismatches, 0)
    aggregate_counts = dict(
        sorted(Counter(str(row["winner"]) for row in aggregate_rows).items())
    )
    _expect_equal(
        "aggregate winner counts", aggregate_counts, expected["aggregate_winners"]
    )

    candidate_counts = dict(
        sorted(Counter(_candidate_invariance(row) for row in selected_rows).items())
    )
    _expect_equal(
        "candidate invariance source counts",
        candidate_counts,
        expected["candidate_invariance"],
    )
    human = _human_diagnostics(case_lock, selected_rows, parquet_rows["human.parquet"])
    for name, value in expected["human_anchors"].items():
        _expect_equal(f"human anchor {name}", human[name], value)

    report, packet = _materialize_packet(
        output_root,
        case_lock,
        selected_rows,
        parquet_rows["human.parquet"],
    )
    baseline_report_counts = _report_invariance_counts(report, "baseline")
    candidate_report_counts = _report_invariance_counts(report, "candidate")
    _expect_equal(
        "baseline emitted invariance",
        baseline_report_counts,
        {"satisfied": 0, "violated": 0, "not_evaluable": len(selected_rows)},
    )
    _expect_equal(
        "candidate emitted invariance",
        candidate_report_counts,
        expected["candidate_invariance"],
    )
    return {
        "case": "case_c",
        "disposition": "PASS",
        "differentiation": "STRONG",
        "fresh_inference_performed": False,
        "conversation_columns_read": False,
        "publication_status": case_lock["publication_status"],
        "source_license_redistribution_status": "UNCLEARED_LOCAL_VALIDATION_ONLY",
        "verified_sources": {
            "raw": {
                "repository": case_lock["raw_source"]["repository"],
                "revision": case_lock["raw_source"]["revision"],
                "path": case_lock["raw_source"]["path"],
                "url": case_lock["raw_source"]["url"],
                "bytes": raw_source.stat().st_size,
                "sha256": _sha256(raw_source),
                "records": len(raw_rows),
                "observed_max_record_bytes": observed_max_record_bytes,
                "declared_license": case_lock["raw_source"]["declared_license"],
            },
            "aggregate_and_human": {
                "dataset": case_lock["dataset"],
                "revision": case_lock["revision"],
                "license": case_lock["license"],
                "url": case_lock["dataset_url"],
                "source_paths": case_lock["source_paths"],
                "verified_local_paths": verified_parquets,
                "artifacts": parquet_artifacts,
            },
            "pair_semantics": {
                "repository": case_lock["pair_semantics"]["repository"],
                "revision": case_lock["pair_semantics"]["revision"],
                "license": case_lock["pair_semantics"]["license"],
                "source_paths": case_lock["pair_semantics"]["source_paths"],
                "verified_local_paths": verified_semantics,
                "source_files": case_lock["pair_semantics"]["source_files"],
            },
            "decoder": {
                **case_lock["decoder"],
                "installed_files_verified": verified_decoder_files,
            },
        },
        "coverage": coverage,
        "selection": selection,
        "raw_game_winner_counts": {
            f"game_{game}": dict(
                sorted(
                    Counter(
                        str(row[f"g{game}_winner"]) for row in selected_rows
                    ).items()
                )
            )
            for game in (1, 2)
        },
        "candidate_invariance": candidate_counts,
        "baseline_invariance": baseline_report_counts,
        "aggregate_crosscheck": {
            "groups": len(aggregate_rows),
            "mismatches": aggregate_mismatches,
            "winner_counts": aggregate_counts,
            "role": "validation_only_not_generic_label_input",
        },
        "human_anchors": human,
        "report": {
            "report_id": report["report_id"],
            "status": report["report_status"],
            "contract_status": report["contract_status"],
            "rule_results": report["rule_results"],
            "invariance": {
                "baseline": baseline_report_counts,
                "candidate": candidate_report_counts,
            },
        },
        "semantic_boundaries": {
            "tie": "generic determinate label",
            "order_inconsistency": "aggregate validation fact only",
            "source_error": "trial error with null label",
            "policy_abstain": "baseline game-2 exclusion",
            "missing_anchor": "explicit ordered-case and group missingness",
        },
        "packet": packet,
        "limitations": [
            "observational fixed-source evidence only",
            "human anchors are non-independent raw annotations",
            "no correctness, population, causal, or stability claim",
            "raw-source redistribution remains uncleared",
        ],
    }


def markdown(result: dict[str, Any]) -> str:
    if result["disposition"] != "PASS":
        return "\n".join(
            (
                "# Case C local validation",
                "",
                "**SOURCE LICENSE / REDISTRIBUTION STATUS = UNCLEARED / LOCAL VALIDATION ONLY**",
                "",
                f"DISPOSITION = {result['disposition']}",
                "",
                f"FAILURE CLASS = {result['failure']['error_class']}",
                "",
                "No publication, release, or source redistribution is authorized.",
                "",
            )
        )
    raw = result["verified_sources"]["raw"]
    selection = result["selection"]
    aggregate = result["aggregate_crosscheck"]
    anchors = result["human_anchors"]
    candidate = result["candidate_invariance"]
    baseline = result["baseline_invariance"]
    lines = [
        "# Case C local validation",
        "",
        "**SOURCE LICENSE / REDISTRIBUTION STATUS = UNCLEARED / LOCAL VALIDATION ONLY**",
        "",
        "The pinned raw artifact was used only for local, metadata-only validation. "
        "No raw prompt, response, or judgment prose is included in this summary.",
        "",
        f"DISPOSITION = {result['disposition']}",
        f"CASE C DIFFERENTIATION = {result['differentiation']}",
        f"PUBLICATION STATUS = {result['publication_status']}",
        f"FRESH INFERENCE PERFORMED = {str(result['fresh_inference_performed']).upper()}",
        "",
        "## Frozen source and selection",
        "",
        f"- Raw revision: `{raw['revision']}`",
        f"- Raw path: `{raw['path']}`",
        f"- Raw bytes / SHA-256 / records: {raw['bytes']} / `{raw['sha256']}` / {raw['records']}",
        f"- Selected groups: {aggregate['groups']}",
        f"- Duplicate rows rejected by the lowest-position rule: {selection['later_duplicate_rows']}",
        f"- Later rows changing two-game outcome identity: {selection['later_duplicate_outcome_changes']}",
        f"- Later rows changing aggregate output: {selection['later_duplicate_aggregate_changes']}",
        "",
        "## Policy migration and invariance",
        "",
        f"- Baseline: {baseline}",
        f"- Candidate: {candidate}",
        "- Baseline game 2 is an explicit `single_order_policy_exclusion` abstention.",
        "- Source `error` remains error/null; aggregate `tie (inconsistent)` never enters the generic label space.",
        "",
        "## Aggregate crosscheck",
        "",
        f"- Exact mappings: {aggregate['groups'] - aggregate['mismatches']}/{aggregate['groups']}",
        f"- Winner counts: {aggregate['winner_counts']}",
        "- The aggregate is validation evidence only, not a substitute for the raw two-game source.",
        "",
        "## Human anchors",
        "",
        f"- Annotations: {anchors['annotations']}",
        f"- Game 1 / game 2 attachments: {anchors['game_1']} / {anchors['game_2']}",
        f"- Anchored ordered cases / groups: {anchors['anchored_ordered_cases']} / {anchors['anchored_groups']}",
        f"- Missing ordered cases / groups: {anchors['missing_ordered_cases']} / {anchors['missing_groups']}",
        f"- Compatible agreements / disagreements: {anchors['compatible_agreements']} / {anchors['compatible_disagreements']}",
        f"- Source-error annotations: {anchors['source_error_annotations']}",
        "- Every annotation is retained independently (`aggregation_method=none`) and clustered by frozen unordered source group.",
        "",
        "## Packet and limitations",
        "",
        f"- Report status / contract status: {result['report']['status']} / {result['report']['contract_status']}",
        "- Canonical JSON, Markdown, and self-contained HTML were emitted by the generic report renderer.",
        "- Evidence is observational and fixed-source; anchors are non-independent.",
        "- No correctness, population, causal, or stability claim is made.",
        "- No publication, release, or source redistribution is authorized.",
        "",
    ]
    return "\n".join(lines)


def _write_validation_result(output_root: Path, result: dict[str, Any]) -> None:
    _write_json(output_root / "case-c-validation.json", result)
    path = output_root / "case-c-validation.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown(result), encoding="utf-8", newline="\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--raw-source", required=True, type=Path)
    parser.add_argument("--semantics-root", required=True, type=Path)
    parser.add_argument("--decoder-path", required=True, type=Path)
    parser.add_argument("--decoder-wheel", required=True, type=Path)
    parser.add_argument("--case-lock", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = validate(
            source_root=args.source_root,
            raw_source=args.raw_source,
            semantics_root=args.semantics_root,
            decoder_path=args.decoder_path,
            decoder_wheel=args.decoder_wheel,
            case_lock_path=args.case_lock,
            output_root=args.out,
        )
    except Exception as error:
        result = {
            "case": "case_c",
            "disposition": "SPEC_OR_UPSTREAM_CONTRADICTION",
            "fresh_inference_performed": False,
            "conversation_columns_read": False,
            "source_license_redistribution_status": "UNCLEARED_LOCAL_VALIDATION_ONLY",
            "failure": {
                "error_class": type(error).__name__,
                "message": str(error)[:500],
            },
        }
        _write_validation_result(args.out, result)
        print(canonical_json_text(result))
        return 2
    _write_validation_result(args.out, result)
    print(
        canonical_json_text(
            {
                "case": result["case"],
                "disposition": result["disposition"],
                "differentiation": result["differentiation"],
                "publication_status": result["publication_status"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
