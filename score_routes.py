#!/usr/bin/env python3
"""Deterministically score graduation-first research routes from JSON input."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any


DIMENSIONS = (
    "completion",
    "resources",
    "foundation",
    "deliverable",
    "safety",
    "reproducibility",
    "clarity",
    "novelty",
)

PRESETS: dict[str, dict[str, float]] = {
    "default": {
        "completion": 25,
        "resources": 20,
        "foundation": 15,
        "deliverable": 15,
        "safety": 10,
        "reproducibility": 5,
        "clarity": 5,
        "novelty": 5,
    },
    "experimental": {
        "completion": 30,
        "resources": 20,
        "foundation": 15,
        "deliverable": 15,
        "safety": 10,
        "reproducibility": 5,
        "clarity": 3,
        "novelty": 2,
    },
    "data-compute": {
        "completion": 25,
        "resources": 15,
        "foundation": 10,
        "deliverable": 20,
        "safety": 10,
        "reproducibility": 10,
        "clarity": 5,
        "novelty": 5,
    },
    "ethics-heavy": {
        "completion": 25,
        "resources": 15,
        "foundation": 10,
        "deliverable": 15,
        "safety": 20,
        "reproducibility": 5,
        "clarity": 5,
        "novelty": 5,
    },
}


def fail(message: str) -> None:
    raise ValueError(message)


def get_weights(payload: dict[str, Any]) -> tuple[str, dict[str, float]]:
    if payload.get("weights") is not None:
        name = "custom"
        raw = payload["weights"]
    else:
        name = str(payload.get("preset", "default"))
        if name not in PRESETS:
            fail(f"unknown preset {name!r}; choose one of {sorted(PRESETS)}")
        raw = PRESETS[name]
    if not isinstance(raw, dict):
        fail("weights must be an object")
    missing = [key for key in DIMENSIONS if key not in raw]
    extra = [key for key in raw if key not in DIMENSIONS]
    if missing or extra:
        fail(f"weights dimension mismatch; missing={missing}, extra={extra}")
    weights = {key: float(raw[key]) for key in DIMENSIONS}
    if any(value < 0 for value in weights.values()) or sum(weights.values()) <= 0:
        fail("weights must be non-negative and sum to more than zero")
    total = sum(weights.values())
    normalized = {key: value * 100.0 / total for key, value in weights.items()}
    return name, normalized


def score_route(route: dict[str, Any], weights: dict[str, float]) -> dict[str, Any]:
    route_id = str(route.get("id", "")).strip()
    if not route_id:
        fail("every route needs a non-empty id")
    scores = route.get("scores")
    if not isinstance(scores, dict):
        fail(f"route {route_id!r} scores must be an object")
    extra = [key for key in scores if key not in DIMENSIONS]
    if extra:
        fail(f"route {route_id!r} has unknown score dimensions: {extra}")

    weighted_sum = 0.0
    known_weight = 0.0
    unknown: list[str] = []
    for key in DIMENSIONS:
        value = scores.get(key)
        if value is None:
            unknown.append(key)
            continue
        number = float(value)
        if not 0 <= number <= 5:
            fail(f"route {route_id!r} score {key!r} must be 0..5 or null")
        weighted_sum += weights[key] * number
        known_weight += weights[key]

    tentative_score = None if known_weight == 0 else 20.0 * weighted_sum / known_weight
    coverage = known_weight
    gate = str(route.get("gate", "amber")).lower()
    if gate not in {"green", "amber", "red"}:
        fail(f"route {route_id!r} gate must be green, amber, or red")
    veto = bool(route.get("veto", False))
    rankable = gate != "red" and not veto and coverage >= 70.0
    return {
        "id": route_id,
        "gate": gate,
        "veto": veto,
        "tentative_score": None if tentative_score is None else round(tentative_score, 2),
        "coverage_percent": round(coverage, 2),
        "unknown_dimensions": unknown,
        "rankable": rankable,
        "rank": None,
    }


def evaluate(payload: dict[str, Any]) -> dict[str, Any]:
    preset, weights = get_weights(payload)
    routes = payload.get("routes")
    if not isinstance(routes, list) or not routes:
        fail("routes must be a non-empty array")
    results = [score_route(route, weights) for route in routes]

    rankable = sorted(
        (item for item in results if item["rankable"]),
        key=lambda item: (
            0 if item["gate"] == "green" else 1,
            -(item["tentative_score"] or 0),
            item["id"],
        ),
    )
    for rank, item in enumerate(rankable, start=1):
        item["rank"] = rank

    warnings: list[str] = []
    if any(not item["rankable"] for item in results):
        warnings.append(
            "Routes with RED/veto status or coverage below 70% are not given a final rank."
        )
    if any(item["unknown_dimensions"] for item in results):
        warnings.append("Unknown dimensions remain null; they were not imputed as 3.")
    return {
        "preset": preset,
        "normalized_weights": {key: round(value, 4) for key, value in weights.items()},
        "routes": results,
        "warnings": warnings,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Score research routes while preserving unknowns and gate status."
    )
    parser.add_argument(
        "input",
        nargs="?",
        default="-",
        help="JSON input file, or - for stdin (default: -)",
    )
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.input == "-":
            payload = json.load(sys.stdin)
        else:
            with open(args.input, encoding="utf-8") as handle:
                payload = json.load(handle)
        if not isinstance(payload, dict):
            fail("top-level JSON must be an object")
        result = evaluate(payload)
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    indent = 2 if args.pretty else None
    print(json.dumps(result, ensure_ascii=False, indent=indent, sort_keys=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
