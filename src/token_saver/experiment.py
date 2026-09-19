"""Execute reproducible paired baseline/Token Saver coding experiments."""

from __future__ import annotations

import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import tempfile
import time
import tarfile
from pathlib import Path
from typing import Any

from .benchmark import (
    MIN_PUBLISHABLE_TASKS,
    MIN_PUBLISHABLE_TRIALS_PER_TASK,
    task_definition_hash,
)
from .install import HOOK_COMMAND, install, user_settings_path
from .sessions import transcript_paths

CONDITIONS = ("baseline", "enabled")


def prompt_sha256(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def _load(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("experiment suite must be a JSON object")
    return payload


def _contains_hook(value: Any) -> bool:
    if isinstance(value, dict):
        return any(_contains_hook(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_hook(item) for item in value)
    return isinstance(value, str) and value.strip() == HOOK_COMMAND


def user_token_saver_hook_configured() -> bool:
    path = user_settings_path()
    if not path.is_file():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return _contains_hook(payload)


def validate_suite(
    suite_path: Path,
    *,
    require_frozen: bool = True,
    require_broad: bool = True,
) -> dict:
    suite_path = suite_path.resolve()
    suite = _load(suite_path)

    if suite.get("suite_version") != 1:
        raise ValueError("suite_version must be 1")

    protocol = suite.get("protocol")
    design = suite.get("design")
    repositories = suite.get("repositories")
    tasks = suite.get("tasks")
    runner = suite.get("runner")

    if not isinstance(protocol, dict):
        raise ValueError("suite requires protocol object")
    if not isinstance(design, dict):
        raise ValueError("suite requires design object")
    if not isinstance(repositories, dict) or not repositories:
        raise ValueError("suite requires repositories object")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("suite requires nonempty tasks list")
    if not isinstance(runner, dict):
        raise ValueError("suite requires runner object")

    trials = design.get("trials_per_task")
    if isinstance(trials, bool) or not isinstance(trials, int) or trials < 1:
        raise ValueError("design.trials_per_task must be a positive integer")
    seed = design.get("condition_order_seed")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("design.condition_order_seed must be an integer")

    command = runner.get("command")
    if not isinstance(command, list) or not command or not all(
        isinstance(item, str) and item for item in command
    ):
        raise ValueError("runner.command must be a nonempty string array")
    model = str(runner.get("model", "")).strip()
    if not model:
        raise ValueError("runner.model is required")
    mode = runner.get("transcript_mode", "claude-project")
    if mode not in {"claude-project", "path"}:
        raise ValueError("runner.transcript_mode must be claude-project or path")

    seen: set[str] = set()
    for task in tasks:
        if not isinstance(task, dict):
            raise ValueError("every task must be an object")
        task_id = str(task.get("id", "")).strip()
        if not task_id or task_id in seen:
            raise ValueError(f"task id missing or duplicated: {task_id!r}")
        seen.add(task_id)
        repo_id = str(task.get("repository", "")).strip()
        if repo_id not in repositories:
            raise ValueError(f"task {task_id}: unknown repository {repo_id!r}")
        repo = repositories[repo_id]
        if not isinstance(repo, dict):
            raise ValueError(f"repository {repo_id}: definition must be an object")
        revision = str(task.get("revision", "")).strip()
        if not revision:
            raise ValueError(f"task {task_id}: revision is required")
        repo_revision = str(repo.get("revision", "")).strip()
        if repo_revision and revision != repo_revision:
            raise ValueError(
                f"task {task_id}: revision must equal repositories.{repo_id}.revision "
                "when the repository pins a single revision"
            )
        prompt = task.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError(f"task {task_id}: prompt is required")
        expected_prompt = str(task.get("prompt_sha256", "")).strip()
        actual_prompt = prompt_sha256(prompt)
        if expected_prompt != actual_prompt:
            raise ValueError(
                f"task {task_id}: prompt_sha256 mismatch; expected {actual_prompt}"
            )
        test_patch = task.get("test_patch")
        if test_patch is not None and (
            not isinstance(test_patch, str) or not test_patch.strip()
        ):
            raise ValueError(f"task {task_id}: test_patch must be a nonempty string")
        verifier = task.get("verifier")
        swebench = task.get("swebench")
        if verifier is None and swebench is None:
            raise ValueError(
                f"task {task_id}: verifier or swebench grader is required"
            )
        if verifier is not None:
            if not isinstance(verifier, list) or not verifier:
                raise ValueError(f"task {task_id}: verifier must contain commands")
            for cmd in verifier:
                if not isinstance(cmd, list) or not cmd or not all(
                    isinstance(arg, str) and arg for arg in cmd
                ):
                    raise ValueError(
                        f"task {task_id}: each verifier command must be a string array"
                    )
        if swebench is not None:
            if not isinstance(swebench, dict):
                raise ValueError(f"task {task_id}: swebench must be an object")
            for field in ("image", "test_command", "env_activate"):
                if not isinstance(swebench.get(field), str) or not swebench[field].strip():
                    raise ValueError(
                        f"task {task_id}: swebench.{field} must be a nonempty string"
                    )
            if not isinstance(test_patch, str) or not test_patch.strip():
                raise ValueError(
                    f"task {task_id}: SWE-bench grading requires test_patch"
                )
            source = task.get("source")
            fail_to_pass = source.get("fail_to_pass") if isinstance(source, dict) else None
            if (
                not isinstance(fail_to_pass, list)
                or not fail_to_pass
                or not all(isinstance(t, str) and t for t in fail_to_pass)
            ):
                raise ValueError(
                    f"task {task_id}: SWE-bench grading requires "
                    "source.fail_to_pass as a nonempty list of test ids"
                )

    if require_broad:
        if len(tasks) < MIN_PUBLISHABLE_TASKS:
            raise ValueError(
                f"broad evidence requires at least {MIN_PUBLISHABLE_TASKS} tasks; "
                f"found {len(tasks)}"
            )
        if trials < MIN_PUBLISHABLE_TRIALS_PER_TASK:
            raise ValueError(
                "broad evidence requires at least "
                f"{MIN_PUBLISHABLE_TRIALS_PER_TASK} trials per task; found {trials}"
            )

    if require_frozen:
        for key in (
            "task_definitions_frozen",
            "condition_order_randomized",
            "independent_verification",
            "history_isolated",
            "hidden_tests_after_agent",
        ):
            if protocol.get(key) is not True:
                raise ValueError(f"protocol.{key} must be true")
        if not str(protocol.get("frozen_at", "")).strip():
            raise ValueError("protocol.frozen_at is required")
        expected = str(protocol.get("task_definition_sha256", "")).strip().lower()
        actual = task_definition_hash(suite)
        if expected != actual:
            raise ValueError(
                "task definition hash mismatch; freeze with "
                f"{actual}"
            )

    return suite


def build_schedule(suite: dict) -> list[dict]:
    design = suite["design"]
    trials = int(design["trials_per_task"])
    seed = int(design["condition_order_seed"])
    rng = random.Random(seed)

    pairs = [
        {"task": task["id"], "trial": trial}
        for task in suite["tasks"]
        for trial in range(1, trials + 1)
    ]
    rng.shuffle(pairs)

    schedule: list[dict] = []
    for pair in pairs:
        conditions = list(CONDITIONS)
        rng.shuffle(conditions)
        for condition in conditions:
            schedule.append({**pair, "condition": condition})
    return schedule


def _git(source: Path, *args: str, strip: bool = True) -> str:
    proc = subprocess.run(
        ["git", "-C", str(source), *args],
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode:
        raise ValueError(
            f"git {' '.join(args)} failed for {source}: {proc.stderr.strip()}"
        )
    return proc.stdout.strip() if strip else proc.stdout


def _validate_repository(source: Path, revision: str) -> str:
    if not source.is_dir():
        raise ValueError(f"repository path not found: {source}")
    resolved = _git(source, "rev-parse", "--verify", f"{revision}^{{commit}}")
    if not resolved:
        raise ValueError(f"revision not found in {source}: {revision}")
    return resolved


def _export_history_isolated_snapshot(
    source: Path,
    revision: str,
    destination: Path,
) -> None:
    """Export one commit without exposing later Git history to the agent."""
    destination.mkdir(parents=True, exist_ok=False)
    proc = subprocess.Popen(
        ["git", "-C", str(source), "archive", "--format=tar", revision],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert proc.stdout is not None
    try:
        with tarfile.open(fileobj=proc.stdout, mode="r|") as archive:
            archive.extractall(destination)
    finally:
        proc.stdout.close()
    stderr = proc.stderr.read().decode("utf-8", "replace") if proc.stderr else ""
    if proc.stderr:
        proc.stderr.close()
    if proc.wait() != 0:
        raise ValueError(
            f"git archive failed for {source}@{revision}: {stderr.strip()}"
        )

    subprocess.run(["git", "init", "-q", str(destination)], check=True)
    _git(destination, "config", "user.email", "token-saver-benchmark@example.invalid")
    _git(destination, "config", "user.name", "Token Saver Benchmark")
    _git(destination, "add", "-A")
    proc = subprocess.run(
        [
            "git", "-C", str(destination), "commit", "-q", "--no-gpg-sign",
            "-m", f"benchmark snapshot {revision}",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode:
        raise ValueError(
            f"failed to initialize isolated benchmark snapshot: {proc.stderr.strip()}"
        )


def _expand_command(
    command: list[str],
    *,
    worktree: Path,
    transcript: Path,
    prompt: str,
    prompt_file: Path,
    model: str,
    condition: str,
) -> list[str]:
    values = {
        "worktree": str(worktree),
        "transcript": str(transcript),
        "prompt": prompt,
        "prompt_file": str(prompt_file),
        "model": model,
        "condition": condition,
    }
    # One pass over each argument: substituted text (e.g. a prompt that itself
    # contains "{model}") is never re-scanned, and unknown braces stay literal.
    placeholder = re.compile(r"\{(" + "|".join(map(re.escape, values)) + r")\}")
    return [
        placeholder.sub(lambda match: values[match.group(1)], item)
        for item in command
    ]


def _run_command(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    stdout_path: Path,
    stderr_path: Path,
    timeout: int,
) -> tuple[int, float]:
    start = time.monotonic()
    try:
        with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
            proc = subprocess.run(
                command,
                cwd=cwd,
                env=env,
                stdout=stdout,
                stderr=stderr,
                timeout=timeout,
                check=False,
            )
    except subprocess.TimeoutExpired:
        return 124, time.monotonic() - start
    return proc.returncode, time.monotonic() - start


def _checkpoint(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _existing_keys(output_path: Path, suite: dict) -> tuple[dict, set[tuple[str, str, str]]]:
    if not output_path.is_file():
        payload = {
            "suite_version": suite["suite_version"],
            "protocol": suite["protocol"],
            "design": suite["design"],
            "repositories": suite["repositories"],
            "runner": suite["runner"],
            "tasks": suite["tasks"],
            "runs": [],
        }
        return payload, set()

    payload = _load(output_path)
    for key in (
        "suite_version", "protocol", "design", "repositories", "runner", "tasks"
    ):
        if payload.get(key) != suite.get(key):
            raise ValueError(
                f"existing result {output_path} does not match suite field {key}"
            )
    keys = {
        (
            str(run.get("task", "")),
            str(run.get("trial", "")),
            str(run.get("condition", "")),
        )
        for run in payload.get("runs", [])
        if isinstance(run, dict)
    }
    return payload, keys


def _swebench_reference_passed(task: dict, ref_dir: Path, *, timeout: int) -> set[str]:
    """Tests passing on the unpatched code with the hidden tests applied.

    Computed once per task and cached, so regressions are judged against what
    the image itself can pass rather than the exit code of the whole command.
    """
    from .swebench_docker import parse_test_statuses, passed_tests, verify_swebench

    swebench = task["swebench"]
    out = ref_dir / "swebench.stdout"
    if not out.is_file():
        ref_dir.mkdir(parents=True, exist_ok=True)
        empty = ref_dir / "empty.patch"
        empty.write_text("", encoding="utf-8")
        test_patch = ref_dir / "hidden-test.patch"
        test_patch.write_text(task["test_patch"], encoding="utf-8")
        rc, _ = verify_swebench(
            image=swebench["image"],
            agent_patch=empty,
            test_patch=test_patch,
            test_command=swebench["test_command"],
            env_activate=swebench["env_activate"],
            stdout_path=out,
            stderr_path=ref_dir / "swebench.stderr",
            timeout=timeout,
        )
        if rc == 124:
            out.unlink(missing_ok=True)
            raise ValueError(f"task {task['id']}: reference verification timed out")
    text = out.read_text(encoding="utf-8", errors="replace")
    if not parse_test_statuses(text):
        out.unlink(missing_ok=True)
        raise ValueError(
            f"task {task['id']}: reference run produced no test results; "
            "check the image and test command"
        )
    return passed_tests(text)


def run_experiment(
    suite_path: Path,
    output_path: Path,
    *,
    dry_run: bool = False,
    allow_development: bool = False,
    allow_user_hook: bool = False,
    only_tasks: set[str] | None = None,
) -> dict:
    suite_path = suite_path.resolve()
    output_path = output_path.resolve()
    suite = validate_suite(
        suite_path,
        require_frozen=not allow_development,
        require_broad=not allow_development,
    )
    all_task_ids = {str(task["id"]) for task in suite["tasks"]}
    selected_ids = set(only_tasks or all_task_ids)
    unknown = sorted(selected_ids - all_task_ids)
    if unknown:
        raise ValueError("unknown experiment task(s): " + ", ".join(unknown))
    if not selected_ids:
        raise ValueError("at least one experiment task must be selected")
    selected_tasks = [
        task for task in suite["tasks"] if str(task["id"]) in selected_ids
    ]
    schedule = [
        item for item in build_schedule(suite) if item["task"] in selected_ids
    ]

    if dry_run:
        return {
            "task_count": len(selected_tasks),
            "trials_per_task": suite["design"]["trials_per_task"],
            "paired_trials": len(schedule) // 2,
            "run_count": len(schedule),
            "schedule": schedule,
            "task_definition_sha256": task_definition_hash(suite),
        }

    if user_token_saver_hook_configured() and not allow_user_hook:
        raise ValueError(
            "user-level 'token-saver hook' is configured. Remove/disable it for "
            "the experiment so the enabled arm is not instrumented twice; the "
            "baseline arm is still protected by TOKEN_SAVER_DISABLED=1."
        )

    base_dir = suite_path.parent
    selected_repo_ids = {str(task["repository"]) for task in selected_tasks}
    repositories: dict[str, Path] = {}
    for repo_id in selected_repo_ids:
        definition = suite["repositories"][repo_id]
        source = (base_dir / str(definition["path"])).resolve()
        if not source.is_dir():
            raise ValueError(f"repository path not found: {source}")
        repositories[repo_id] = source

    resolved_revisions: dict[tuple[str, str], str] = {}
    for task in selected_tasks:
        repo_id = str(task["repository"])
        revision = str(task["revision"]).strip()
        key = (repo_id, revision)
        if key not in resolved_revisions:
            resolved_revisions[key] = _validate_repository(
                repositories[repo_id],
                revision,
            )

    result, completed = _existing_keys(output_path, suite)
    tasks = {task["id"]: task for task in selected_tasks}
    runner = suite["runner"]
    model = str(runner["model"])
    timeout = int(runner.get("timeout_seconds", 1800))
    if timeout < 1:
        raise ValueError("runner.timeout_seconds must be positive")
    extra_env = runner.get("env", {})
    if not isinstance(extra_env, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in extra_env.items()
    ):
        raise ValueError("runner.env must be a string-to-string object")

    artifacts = output_path.parent / (output_path.stem + ".artifacts")

    for sequence, item in enumerate(schedule, start=1):
        key = (item["task"], str(item["trial"]), item["condition"])
        if key in completed:
            continue

        task = tasks[item["task"]]
        source = repositories[task["repository"]]
        revision = resolved_revisions[(task["repository"], str(task["revision"]).strip())]
        run_dir = artifacts / item["task"] / f"trial-{item['trial']}" / item["condition"]
        run_dir.mkdir(parents=True, exist_ok=True)
        transcript = run_dir / "transcript.jsonl"
        prompt_file = run_dir / "prompt.txt"
        prompt_file.write_text(task["prompt"], encoding="utf-8")
        stdout_path = run_dir / "agent.stdout"
        stderr_path = run_dir / "agent.stderr"

        with tempfile.TemporaryDirectory(prefix="token-saver-e2e-") as tmp:
            worktree = Path(tmp) / "repo"
            _export_history_isolated_snapshot(source, revision, worktree)
            try:
                for setup in task.get("setup", []):
                    setup_proc = subprocess.run(
                        setup,
                        cwd=worktree,
                        text=True,
                        capture_output=True,
                        check=False,
                    )
                    if setup_proc.returncode:
                        raise ValueError(
                            f"task {task['id']}: setup failed: {' '.join(setup)}\n"
                            + setup_proc.stderr[-2000:]
                        )

                settings_path = worktree / ".claude" / "settings.json"
                original_settings = (
                    settings_path.read_bytes() if settings_path.is_file() else None
                )

                env = os.environ.copy()
                env.update(extra_env)
                env["TOKEN_SAVER_BENCHMARK_CONDITION"] = item["condition"]
                env["TOKEN_SAVER_BENCHMARK_TASK"] = task["id"]
                env["TOKEN_SAVER_BENCHMARK_TRIAL"] = str(item["trial"])
                if item["condition"] == "baseline":
                    env["TOKEN_SAVER_DISABLED"] = "1"
                else:
                    env.pop("TOKEN_SAVER_DISABLED", None)
                    install(worktree)

                before = set(transcript_paths(worktree))
                command = _expand_command(
                    runner["command"],
                    worktree=worktree,
                    transcript=transcript,
                    prompt=task["prompt"],
                    prompt_file=prompt_file,
                    model=model,
                    condition=item["condition"],
                )
                agent_rc, seconds = _run_command(
                    command,
                    cwd=worktree,
                    env=env,
                    stdout_path=stdout_path,
                    stderr_path=stderr_path,
                    timeout=timeout,
                )
                if agent_rc != 0:
                    stdout_tail = stdout_path.read_text(
                        encoding="utf-8", errors="replace"
                    )[-2000:]
                    stderr_tail = stderr_path.read_text(
                        encoding="utf-8", errors="replace"
                    )[-2000:]
                    raise ValueError(
                        f"task {task['id']} trial {item['trial']} "
                        f"{item['condition']}: agent runner exited {agent_rc}\n"
                        f"stdout tail:\n{stdout_tail}\n"
                        f"stderr tail:\n{stderr_tail}"
                    )

                mode = runner.get("transcript_mode", "claude-project")
                if mode == "claude-project":
                    after = set(transcript_paths(worktree))
                    created = sorted(after - before)
                    if len(created) != 1:
                        raise ValueError(
                            f"task {task['id']} trial {item['trial']} "
                            f"{item['condition']}: expected exactly one new Claude "
                            f"transcript, found {len(created)}"
                        )
                    shutil.copyfile(created[0], transcript)
                elif not transcript.is_file():
                    raise ValueError(
                        f"runner did not create transcript: {transcript}"
                    )

                # Remove benchmark instrumentation before capturing the solution.
                # The enabled arm creates .claude/settings.json so its hook can run,
                # but that file is not part of the agent's solution and must never
                # be sent to the independent grader.
                if item["condition"] == "enabled":
                    if original_settings is None:
                        settings_path.unlink(missing_ok=True)
                        try:
                            settings_path.parent.rmdir()
                        except OSError:
                            pass
                    else:
                        settings_path.parent.mkdir(parents=True, exist_ok=True)
                        settings_path.write_bytes(original_settings)

                # Stage the complete working tree so new/deleted files are included
                # in the patch as well as modifications to tracked files.
                _git(worktree, "add", "-A")
                agent_patch = run_dir / "agent.patch"
                agent_patch.write_text(
                    # strip=False: a patch without its final newline is "corrupt"
                    _git(worktree, "diff", "--cached", "--binary", strip=False),
                    encoding="utf-8",
                )

                verification = []
                verifier_ok = True
                test_patch = task.get("test_patch")
                swebench = task.get("swebench")
                if swebench is not None:
                    from .swebench_docker import (
                        grade_swebench,
                        passed_tests,
                        strip_test_file_changes,
                        verify_swebench,
                    )

                    verifier_timeout = int(task.get("verifier_timeout_seconds", timeout))
                    test_patch_path = run_dir / "hidden-test.patch"
                    test_patch_path.write_text(test_patch, encoding="utf-8")
                    graded_patch = run_dir / "agent.graded.patch"
                    graded_patch.write_text(
                        strip_test_file_changes(
                            agent_patch.read_text(encoding="utf-8"), test_patch
                        ),
                        encoding="utf-8",
                    )
                    reference_passed = _swebench_reference_passed(
                        task,
                        artifacts / "_reference" / item["task"],
                        timeout=verifier_timeout,
                    )
                    verify_out = run_dir / "swebench.stdout"
                    verify_err = run_dir / "swebench.stderr"
                    rc, elapsed = verify_swebench(
                        image=swebench["image"],
                        agent_patch=graded_patch,
                        test_patch=test_patch_path,
                        test_command=swebench["test_command"],
                        env_activate=swebench["env_activate"],
                        stdout_path=verify_out,
                        stderr_path=verify_err,
                        timeout=verifier_timeout,
                    )
                    grade = grade_swebench(
                        task["source"]["fail_to_pass"],
                        reference_passed,
                        passed_tests(verify_out.read_text(encoding="utf-8", errors="replace")),
                    )
                    verification.append({
                        "kind": "swebench_docker",
                        "image": swebench["image"],
                        "test_command": swebench["test_command"],
                        "exit_code": rc,
                        "seconds": elapsed,
                        "graded_patch": str(graded_patch.relative_to(output_path.parent)),
                        "grade": grade,
                        "stdout": str(verify_out.relative_to(output_path.parent)),
                        "stderr": str(verify_err.relative_to(output_path.parent)),
                    })
                    verifier_ok = grade["resolved"] and rc != 124
                else:
                    if test_patch:
                        patch_stdout = run_dir / "test-patch.stdout"
                        patch_stderr = run_dir / "test-patch.stderr"
                        start = time.monotonic()
                        with patch_stdout.open("wb") as stdout, patch_stderr.open("wb") as stderr:
                            patch_proc = subprocess.run(
                                ["git", "apply", "--whitespace=nowarn", "-"],
                                cwd=worktree,
                                env=env,
                                input=test_patch.encode("utf-8"),
                                stdout=stdout,
                                stderr=stderr,
                                check=False,
                            )
                        verification.append({
                            "kind": "hidden_test_patch",
                            "exit_code": patch_proc.returncode,
                            "seconds": time.monotonic() - start,
                            "stdout": str(patch_stdout.relative_to(output_path.parent)),
                            "stderr": str(patch_stderr.relative_to(output_path.parent)),
                        })
                        verifier_ok = patch_proc.returncode == 0

                    for index, verifier in enumerate(task["verifier"], start=1):
                        verify_out = run_dir / f"verify-{index}.stdout"
                        verify_err = run_dir / f"verify-{index}.stderr"
                        verify_env = env.copy()
                        verify_env["TOKEN_SAVER_DISABLED"] = "1"
                        rc, elapsed = _run_command(
                            verifier,
                            cwd=worktree,
                            env=verify_env,
                            stdout_path=verify_out,
                            stderr_path=verify_err,
                            timeout=int(task.get("verifier_timeout_seconds", timeout)),
                        )
                        verification.append(
                            {
                                "command": verifier,
                                "exit_code": rc,
                                "seconds": elapsed,
                                "stdout": str(verify_out.relative_to(output_path.parent)),
                                "stderr": str(verify_err.relative_to(output_path.parent)),
                            }
                        )
                        verifier_ok = verifier_ok and rc == 0

                success = agent_rc == 0 and verifier_ok
                validation = (
                    "independent verifier passed"
                    if success
                    else "independent verifier failed or agent exited nonzero"
                )
                run = {
                    "task": task["id"],
                    "trial": item["trial"],
                    "condition": item["condition"],
                    "sequence": sequence,
                    "revision": task["revision"],
                    "model": model,
                    "prompt_sha256": task["prompt_sha256"],
                    "success": success,
                    "validation": validation,
                    "manual_intervention": False,
                    "seconds": seconds,
                    "agent_exit_code": agent_rc,
                    "verification": verification,
                    "agent_patch": str(agent_patch.relative_to(output_path.parent)),
                    "transcripts": [
                        str(transcript.relative_to(output_path.parent))
                    ],
                }
                result["runs"].append(run)
                _checkpoint(output_path, result)
                completed.add(key)
            finally:
                pass

    return result
