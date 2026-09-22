"""The token cap on the code map — the thing that makes it usable on real repos."""

import textwrap

import pytest

from acco.estimate import estimate_tokens
from acco.skeleton import build_map, file_priority


@pytest.fixture
def big_repo(tmp_path):
    """A repo far larger than any budget we will hand it."""
    for area in ("src", "tests", "examples"):
        (tmp_path / area).mkdir()
        for n in range(12):
            body = "\n".join(f"    step_{i}(value, {i})" for i in range(30))
            (tmp_path / area / f"mod{n}.py").write_text(
                textwrap.dedent(
                    f"""\
                    import os

                    class Service{n}:
                        def run(self, payload: dict) -> int:
                    """
                )
                + body
                + "\n"
            )
    (tmp_path / "README.md").write_text("# Project\n\nprose\n" * 50)
    return tmp_path


@pytest.mark.parametrize("cap", [500, 1000, 2500, 5000, 20000])
def test_map_never_exceeds_its_cap(big_repo, cap):
    """Regression: an uncapped map of a real repo does not fit in any window."""
    out = build_map(big_repo, max_tokens=cap)
    assert estimate_tokens(out) <= cap, f"cap={cap}"


@pytest.mark.parametrize("cap", [400, 700, 1000])
def test_map_uses_the_budget_it_is_given(big_repo, cap):
    """Regression: the packer bailed at the first oversized file, returning 12%.

    Only meaningful when the cap actually truncates — a complete map that fits
    is not padded to fill the budget.
    """
    out = build_map(big_repo, max_tokens=cap)
    assert "listed=0" not in out, "cap must be small enough to truncate"
    assert estimate_tokens(out) >= cap * 0.5, f"cap={cap} badly under-filled"


def test_a_cap_larger_than_the_repo_returns_the_complete_map(big_repo):
    out = build_map(big_repo, max_tokens=50_000)
    assert "listed=0" in out
    assert "not expanded" not in out


def test_every_file_is_still_accounted_for(big_repo):
    """Dropping a file silently is worse than listing it."""
    out = build_map(big_repo, max_tokens=800)
    assert "not expanded" in out
    header = [ln for ln in out.splitlines() if ln.startswith("# files=")][0]
    assert "files=37" in header


def test_uncapped_map_is_unchanged(big_repo):
    out = build_map(big_repo)
    assert "not expanded" not in out
    assert "Service0" in out


@pytest.mark.parametrize("cap", [300, 500, 700, 900])
def test_low_priority_files_never_displace_high_priority_ones(big_repo, cap):
    """The contract is ordering, not exclusion.

    Filling leftover budget with tests is fine once nothing better is left; a
    test file appearing *while a src file is still missing* is not.
    """
    out = build_map(big_repo, max_tokens=cap)
    expanded = {ln[3:].strip() for ln in out.splitlines() if ln.startswith("## ")}
    src = {f"src/mod{n}.py" for n in range(12)}
    low = {f"tests/mod{n}.py" for n in range(12)} | {
        f"examples/mod{n}.py" for n in range(12)
    }
    if expanded & low:
        assert src <= expanded, (
            f"cap={cap}: low-priority files expanded while src files were dropped"
        )


def test_the_entry_point_survives_the_tightest_budget(big_repo):
    out = build_map(big_repo, max_tokens=300)
    assert "## README.md" in out


def test_priority_ordering():
    assert file_priority("README.md") < file_priority("src/util.py")
    assert file_priority("src/util.py") < file_priority("tests/test_util.py")
    assert file_priority("src/__init__.py") < file_priority("examples/demo.py")


def test_cap_smaller_than_one_file_still_returns_an_index(big_repo):
    out = build_map(big_repo, max_tokens=120)
    assert estimate_tokens(out) <= 120
    assert "CODE MAP" in out
