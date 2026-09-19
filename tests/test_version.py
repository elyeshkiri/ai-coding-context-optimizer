import tomllib
from pathlib import Path

import token_saver


def test_runtime_version_matches_project_metadata():
    root = Path(__file__).resolve().parents[1]
    with (root / "pyproject.toml").open("rb") as handle:
        project_version = tomllib.load(handle)["project"]["version"]
    assert token_saver.__version__ == project_version
