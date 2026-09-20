"""Adaptive output budgets and quality-gated calibration.

Runtime adaptation is deterministic and bounded. Calibration never learns from
failed, blocked, unblinded, or materially lower-quality Token Saver responses.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
import re
from pathlib import Path

from .output_saver import OUTPUT_MODES, OUTPUT_TASKS, build_output_policy

CALIBRATION_SCHEMA = 1
DEFAULT_CALIBRATION_FILE = ".token-saver.output-calibration.json"

_MODE_BOUNDS = {
    "terse": (150, 900),
    "normal": (250, 2200),
    "detailed": (700, 4000),
}
_COMPLEXITY_MULTIPLIERS = {
    "simple": 0.70,
    "standard": 1.00,
    "complex": 1.25,
    "extended": 1.50,
}
_SCOPE_RE = re.compile(
    r"\b(end[- ]to[- ]end|across|multiple|repository|architecture|benchmark|"
    r"migration|migrate|refactor|release|integration|ci/cd|pipeline|compare|"
    r"all files|all modules|full project|production)\b",
    re.IGNORECASE,
)
_CODE_RE = re.compile(
    r"```|traceback|exception:|error:|\b[a-zA-Z0-9_.-]+\.(py|js|ts|tsx|jsx|go|rs|java|rb|php):\d+",
    re.IGNORECASE,
)
_LIST_RE = re.compile(r"(?m)^\s*(?:[-*]|\d+[.)])\s+")
_SIMPLE_EXPLANATION_RE = re.compile(
    r"^\s*(what is|what are|why is|why does|how does|difference between)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class BudgetDecision:
    """Describe one bounded adaptive output-budget decision."""

    task: str
    mode: str
    base_tokens: int
    max_tokens: int
    complexity_score: int
    complexity_tier: str
    multiplier: float
    calibrated: bool
    calibration_samples: int
    reasons: tuple[str, ...]

    def to_dict(self) -> dict:
        """Return a machine-readable representation."""
        return {
            "task": self.task,
            "mode": self.mode,
            "base_tokens": self.base_tokens,
            "max_tokens": self.max_tokens,
            "complexity_score": self.complexity_score,
            "complexity_tier": self.complexity_tier,
            "multiplier": self.multiplier,
            "calibrated": self.calibrated,
            "calibration_samples": self.calibration_samples,
            "reasons": list(self.reasons),
        }


def _complexity(prompt: str, task: str) -> tuple[int, tuple[str, ...]]:
    """Score visible task complexity using deterministic prompt structure only."""
    text = " ".join(prompt.strip().split())
    words = len(text.split())
    score = 0
    reasons: list[str] = []

    if words >= 24:
        score += 1
        reasons.append("prompt>=24_words")
    if words >= 80:
        score += 1
        reasons.append("prompt>=80_words")
    if len(_LIST_RE.findall(prompt)) >= 3:
        score += 1
        reasons.append("multi_part_request")
    if _CODE_RE.search(prompt):
        score += 1
        reasons.append("code_or_diagnostic_evidence")
    if _SCOPE_RE.search(prompt):
        score += 1
        reasons.append("broad_scope")

    if (
        task == "explanation"
        and words <= 12
        and _SIMPLE_EXPLANATION_RE.search(text)
        and not _CODE_RE.search(prompt)
    ):
        score -= 1
        reasons.append("simple_explanation")

    return score, tuple(reasons)


def _tier(score: int) -> str:
    """Map a complexity score to a stable budget tier."""
    if score <= 0:
        return "simple"
    if score == 1:
        return "standard"
    if score == 2:
        return "complex"
    return "extended"


def _clamp(value: int, lower: int, upper: int) -> int:
    """Clamp an integer into inclusive safety bounds."""
    return max(lower, min(upper, value))


def _percentile(values: list[int], percentile: float) -> float:
    """Return a linearly interpolated percentile for a non-empty sample."""
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(ordered[lower])
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def load_output_calibration(path: Path | None) -> dict:
    """Load a calibration artifact, returning an empty mapping when absent."""
    if path is None or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(payload, dict) or payload.get("schema") != CALIBRATION_SCHEMA:
        return {}
    recommendations = payload.get("recommendations")
    return recommendations if isinstance(recommendations, dict) else {}


def _calibrated_base(
    calibration: dict,
    task: str,
    mode: str,
    fallback: int,
) -> tuple[int, bool, int]:
    """Return a learned base only when the artifact contains valid evidence."""
    task_data = calibration.get(task)
    if not isinstance(task_data, dict):
        return fallback, False, 0
    mode_data = task_data.get(mode)
    if not isinstance(mode_data, dict):
        return fallback, False, 0
    budget = mode_data.get("recommended_tokens")
    samples = mode_data.get("samples")
    if (
        isinstance(budget, int)
        and not isinstance(budget, bool)
        and budget > 0
        and isinstance(samples, int)
        and not isinstance(samples, bool)
        and samples >= 3
    ):
        return budget, True, samples
    return fallback, False, 0


def adaptive_output_budget(
    prompt: str,
    *,
    task: str,
    mode: str,
    calibration: dict | None = None,
    min_tokens: int | None = None,
    max_tokens: int | None = None,
) -> BudgetDecision:
    """Choose a deterministic bounded budget from task, mode, and prompt complexity."""
    normalized_task = task.strip().lower()
    normalized_mode = mode.strip().lower()
    if normalized_task not in OUTPUT_TASKS:
        raise ValueError(f"unknown adaptive output task: {task}")
    if normalized_mode not in OUTPUT_MODES:
        raise ValueError(f"unknown adaptive output mode: {mode}")

    static_base = build_output_policy(normalized_mode, task=normalized_task).max_tokens
    learned_base, calibrated, samples = _calibrated_base(
        calibration or {}, normalized_task, normalized_mode, static_base
    )
    score, reasons = _complexity(prompt, normalized_task)
    tier = _tier(score)
    multiplier = _COMPLEXITY_MULTIPLIERS[tier]

    mode_min, mode_max = _MODE_BOUNDS[normalized_mode]
    lower = mode_min if min_tokens is None else max(mode_min, min_tokens)
    upper = mode_max if max_tokens is None else min(mode_max, max_tokens)
    if lower > upper:
        raise ValueError("adaptive output min_tokens cannot exceed max_tokens")

    budget = _clamp(round(learned_base * multiplier), lower, upper)
    return BudgetDecision(
        task=normalized_task,
        mode=normalized_mode,
        base_tokens=learned_base,
        max_tokens=budget,
        complexity_score=score,
        complexity_tier=tier,
        multiplier=multiplier,
        calibrated=calibrated,
        calibration_samples=samples,
        reasons=reasons,
    )


def _weighted_quality(quality: dict) -> float:
    """Return the evaluator-compatible weighted response quality score."""
    weights = {
        "correctness": 0.40,
        "completeness": 0.20,
        "actionability": 0.15,
        "safety": 0.15,
        "concision": 0.10,
    }
    total = 0.0
    for name, weight in weights.items():
        value = quality.get(name)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"quality.{name} must be numeric for calibration")
        total += float(value) * weight
    return total


def _pair_is_safe_for_calibration(baseline: dict, optimized: dict) -> bool:
    """Return whether a paired run preserves success and response quality."""
    if not baseline.get("success") or not optimized.get("success"):
        return False
    if optimized.get("blocker", False):
        return False
    base_quality = baseline.get("quality")
    optimized_quality = optimized.get("quality")
    if not isinstance(base_quality, dict) or not isinstance(optimized_quality, dict):
        return False
    if float(optimized_quality.get("correctness", 0)) < float(
        base_quality.get("correctness", 0)
    ) - 0.10:
        return False
    if float(optimized_quality.get("safety", 0)) < float(
        base_quality.get("safety", 0)
    ) - 0.10:
        return False
    return _weighted_quality(optimized_quality) >= _weighted_quality(base_quality) - 0.10


def calibrate_output_budgets(path: Path, *, margin: float = 1.15) -> dict:
    """Build learned task/mode budgets from blind, quality-preserving paired runs."""
    if margin < 1.0 or margin > 2.0:
        raise ValueError("calibration margin must be between 1.0 and 2.0")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("calibration manifest must be a JSON object")
    quality_meta = payload.get("quality_evaluation")
    if not isinstance(quality_meta, dict) or quality_meta.get("blinded") is not True:
        raise ValueError("output calibration requires blinded quality evidence")
    runs = payload.get("runs")
    if not isinstance(runs, list) or not runs:
        raise ValueError("output calibration requires a non-empty runs list")

    pairs: dict[tuple[str, int], dict[str, dict]] = {}
    for run in runs:
        if not isinstance(run, dict):
            continue
        task_id = str(run.get("task") or "").strip()
        condition = str(run.get("condition") or "")
        trial = run.get("trial", 1)
        if not task_id or condition not in {"baseline", "token-saver"}:
            continue
        if isinstance(trial, bool) or not isinstance(trial, int) or trial <= 0:
            continue
        pair = pairs.setdefault((task_id, trial), {})
        if condition in pair:
            raise ValueError(
                f"duplicate {condition} calibration run for task/trial: "
                f"{task_id}/{trial}"
            )
        pair[condition] = run

    samples: dict[tuple[str, str], list[tuple[str, int]]] = {}
    for pair in pairs.values():
        if set(pair) != {"baseline", "token-saver"}:
            continue
        baseline = pair["baseline"]
        optimized = pair["token-saver"]
        if not _pair_is_safe_for_calibration(baseline, optimized):
            continue
        task = str(optimized.get("output_task") or "").strip().lower()
        mode = str(optimized.get("output_mode") or "normal").strip().lower()
        output_tokens = optimized.get("output_tokens")
        if task not in OUTPUT_TASKS or mode not in OUTPUT_MODES:
            continue
        if (
            isinstance(output_tokens, bool)
            or not isinstance(output_tokens, int)
            or output_tokens <= 0
        ):
            continue
        samples.setdefault((task, mode), []).append((str(optimized["task"]), output_tokens))

    recommendations: dict[str, dict[str, dict]] = {}
    for (task, mode), records in sorted(samples.items()):
        task_ids = {task_id for task_id, _ in records}
        if len(records) < 3 or len(task_ids) < 3:
            continue
        values = [output_tokens for _, output_tokens in records]
        p90 = _percentile(values, 0.90)
        lower, upper = _MODE_BOUNDS[mode]
        recommended = _clamp(math.ceil(p90 * margin), lower, upper)
        recommendations.setdefault(task, {})[mode] = {
            "recommended_tokens": recommended,
            "samples": len(values),
            "tasks": len(task_ids),
            "p90_output_tokens": p90,
            "margin": margin,
        }

    return {
        "schema": CALIBRATION_SCHEMA,
        "source": str(path),
        "quality_gate": "blind paired success + correctness/safety/weighted parity",
        "recommendations": recommendations,
    }
