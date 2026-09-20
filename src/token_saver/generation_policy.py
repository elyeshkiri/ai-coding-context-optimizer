"""Automatic generation-policy selection for supported coding-agent hooks.

The classifier is deliberately deterministic and conservative. Ambiguous
follow-ups inherit the active task policy instead of causing policy churn.
No prompt text is persisted; session state stores only the resolved policy.
"""

from __future__ import annotations

import re
from pathlib import Path

from .output_saver import OUTPUT_MODES, OUTPUT_TASKS, build_output_policy
from .policy import looks_like_new_task
from .state import update as update_state

AUTO_OUTPUT_TASK = "auto"
OUTPUT_TASK_OPTIONS = (AUTO_OUTPUT_TASK, *OUTPUT_TASKS)

_DEBUG_RE = re.compile(
    r"\b(debug|bug|bugs|error|errors|exception|traceback|failing|failure|"
    r"regression|broken|crash|crashes|not working|doesn't work|does not work)\b",
    re.IGNORECASE,
)
_REVIEW_RE = re.compile(
    r"\b(review|audit|code review|pull request|merge request|pr|mr|"
    r"inspect changes|review diff|assessment)\b",
    re.IGNORECASE,
)
_PLAN_RE = re.compile(
    r"\b(plan|planning|roadmap|architecture|architectural|strategy|proposal|"
    r"design approach|technical design|system design)\b",
    re.IGNORECASE,
)
_CODING_RE = re.compile(
    r"\b(implement|implementation|build|create|add|remove|rename|refactor|"
    r"migrate|patch|write code|modify|update code|change code|feature|"
    r"integrate|integration)\b",
    re.IGNORECASE,
)
_EXPLANATION_RE = re.compile(
    r"(^|\b)(explain|why|what is|what are|how does|how do|difference between|"
    r"meaning of|teach me|walk me through)\b",
    re.IGNORECASE,
)
_TERSE_RE = re.compile(
    r"\b(brief|briefly|concise|concisely|short answer|keep it short|terse)\b",
    re.IGNORECASE,
)
_DETAILED_RE = re.compile(
    r"\b(detailed|in detail|deep dive|comprehensive|thorough|step by step|"
    r"step-by-step|full explanation|full report)\b",
    re.IGNORECASE,
)


def classify_output_task(prompt: str) -> str | None:
    """Return a high-confidence output task class, or None when ambiguous."""
    text = " ".join(prompt.strip().split())
    if not text:
        return None
    if _DEBUG_RE.search(text):
        return "debugging"
    if _REVIEW_RE.search(text):
        return "review"
    if _PLAN_RE.search(text):
        return "planning"
    if _CODING_RE.search(text):
        return "coding"
    if _EXPLANATION_RE.search(text) or text.rstrip().endswith("?"):
        return "explanation"
    return None


def explicit_output_mode(prompt: str) -> str | None:
    """Return an explicitly requested verbosity mode when the prompt states one."""
    if _DETAILED_RE.search(prompt):
        return "detailed"
    if _TERSE_RE.search(prompt):
        return "terse"
    return None


def automatic_output_policy(
    root: Path,
    prompt: str,
    *,
    session_id: str | None = None,
    mode: str = "normal",
    task: str = AUTO_OUTPUT_TASK,
) -> str | None:
    """Return a generation policy only when the resolved session policy changes.

    In auto task mode, high-confidence prompts choose a task class. Ambiguous
    follow-ups inherit the current class. Explicit new-task language clears that
    inheritance. User-requested terse/detailed wording overrides the configured
    mode for the active task.
    """
    configured_mode = mode.strip().lower()
    if configured_mode not in OUTPUT_MODES:
        raise ValueError(
            f"unknown automatic output mode {mode!r}; expected one of: "
            + ", ".join(OUTPUT_MODES)
        )
    configured_task = task.strip().lower()
    if configured_task not in OUTPUT_TASK_OPTIONS:
        raise ValueError(
            f"unknown automatic output task {task!r}; expected one of: "
            + ", ".join(OUTPUT_TASK_OPTIONS)
        )

    detected_task = (
        classify_output_task(prompt)
        if configured_task == AUTO_OUTPUT_TASK
        else configured_task
    )
    requested_mode = explicit_output_mode(prompt)
    new_task = looks_like_new_task(prompt)
    decision: dict[str, object] = {}

    def mutate(data: dict) -> None:
        previous = data.get("output_policy")
        if not isinstance(previous, dict):
            previous = {}

        previous_task = str(previous.get("task") or "")
        previous_mode = str(previous.get("mode") or "")

        if configured_task != AUTO_OUTPUT_TASK:
            resolved_task = configured_task
        elif detected_task:
            resolved_task = detected_task
        elif previous_task in OUTPUT_TASKS and not new_task:
            resolved_task = previous_task
        else:
            resolved_task = "general"

        if requested_mode:
            resolved_mode = requested_mode
        elif (
            previous_mode in OUTPUT_MODES
            and previous_task == resolved_task
            and not new_task
        ):
            resolved_mode = previous_mode
        else:
            resolved_mode = configured_mode

        signature = f"{resolved_mode}:{resolved_task}"
        previous_signature = str(previous.get("signature") or "")
        if previous_signature == signature and not new_task:
            return

        policy = build_output_policy(resolved_mode, task=resolved_task)
        data["output_policy"] = {
            "signature": signature,
            "mode": policy.mode,
            "task": policy.task,
            "max_tokens": policy.max_tokens,
        }
        decision["policy"] = policy

    update_state(root, mutate, session_id)
    policy = decision.get("policy")
    if policy is None:
        return None

    return (
        "TOKEN SAVER GENERATION POLICY — apply for this task until it changes:\n"
        + policy.instructions
    )
