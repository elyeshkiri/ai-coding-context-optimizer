import re
from pathlib import Path

import token_saver


def test_runtime_version_matches_project_metadata():
    root = Path(__file__).resolve().parents[1]
    text = (root / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'(?m)^version\s*=\s*"([^"]+)"\s*$', text)
    assert match is not None
    assert token_saver.__version__ == match.group(1)
