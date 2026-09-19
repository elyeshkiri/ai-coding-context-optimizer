#!/usr/bin/env python3
"""Collect recent per-PR ranking-diff artifacts from GitHub Actions."""

from __future__ import annotations

import argparse
from io import BytesIO
import json
import os
from pathlib import Path
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen
from zipfile import BadZipFile, ZipFile

API_VERSION = "2022-11-28"


class _CrossHostSafeRedirect(HTTPRedirectHandler):
    """Follow redirects while stripping GitHub auth from cross-host requests."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        """Remove Authorization when a redirect leaves the original API host."""
        redirected = super().redirect_request(
            req,
            fp,
            code,
            msg,
            headers,
            newurl,
        )
        if (
            redirected is not None
            and urlparse(req.full_url).netloc != urlparse(newurl).netloc
        ):
            redirected.remove_header("Authorization")
        return redirected


def _request(url: str, token: str) -> Request:
    """Build one authenticated GitHub API request."""
    return Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "token-saver-ranking-calibration",
            "X-GitHub-Api-Version": API_VERSION,
        },
    )


def _fetch_json(url: str, token: str) -> dict:
    """Fetch one JSON object from the GitHub API."""
    with urlopen(_request(url, token), timeout=30) as response:
        payload = json.load(response)
    if not isinstance(payload, dict):
        raise ValueError(f"GitHub API returned non-object JSON: {url}")
    return payload


def list_recent_ranking_artifacts(
    repository: str,
    token: str,
    *,
    limit: int,
) -> list[dict]:
    """Return the newest non-expired ranking artifact per pull request."""
    if limit <= 0:
        raise ValueError("limit must be positive")

    selected: list[dict] = []
    seen_names: set[str] = set()
    page = 1
    while len(selected) < limit:
        url = (
            f"https://api.github.com/repos/{repository}/actions/artifacts"
            f"?per_page=100&page={page}"
        )
        payload = _fetch_json(url, token)
        artifacts = payload.get("artifacts")
        if not isinstance(artifacts, list) or not artifacts:
            break

        for artifact in artifacts:
            if not isinstance(artifact, dict) or artifact.get("expired") is True:
                continue
            name = artifact.get("name")
            artifact_id = artifact.get("id")
            download_url = artifact.get("archive_download_url")
            if (
                not isinstance(name, str)
                or not name.startswith("ranking-regression-")
                or name in seen_names
                or not isinstance(artifact_id, int)
                or not isinstance(download_url, str)
            ):
                continue
            seen_names.add(name)
            selected.append(
                {
                    "id": artifact_id,
                    "name": name,
                    "created_at": artifact.get("created_at"),
                    "archive_download_url": download_url,
                    "workflow_run": artifact.get("workflow_run"),
                }
            )
            if len(selected) >= limit:
                break

        if len(artifacts) < 100:
            break
        page += 1
    return selected


def _extract_ranking_diff(archive: bytes) -> bytes:
    """Extract ranking-diff.json from one Actions artifact ZIP."""
    try:
        with ZipFile(BytesIO(archive)) as bundle:
            matches = [
                name
                for name in bundle.namelist()
                if Path(name).name == "ranking-diff.json"
            ]
            if len(matches) != 1:
                raise ValueError(
                    "ranking artifact must contain exactly one ranking-diff.json"
                )
            return bundle.read(matches[0])
    except BadZipFile as exc:
        raise ValueError("GitHub artifact response was not a ZIP archive") from exc


def _download_archive(url: str, token: str) -> bytes:
    """Download one artifact ZIP without leaking GitHub auth to blob storage."""
    opener = build_opener(_CrossHostSafeRedirect())
    with opener.open(_request(url, token), timeout=60) as response:
        return response.read()


def download_ranking_history(
    artifacts: list[dict],
    token: str,
    output: Path,
) -> None:
    """Download selected artifact diffs into a local history directory."""
    output.mkdir(parents=True, exist_ok=True)
    for artifact in artifacts:
        artifact_id = int(artifact["id"])
        url = str(artifact["archive_download_url"])
        diff = _extract_ranking_diff(_download_archive(url, token))
        (output / f"{artifact_id}.json").write_bytes(diff)


def main(argv: list[str] | None = None) -> int:
    """Collect ranking artifacts using GitHub Actions environment credentials."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("ranking-history"))
    parser.add_argument(
        "--selection-out",
        type=Path,
        default=Path("selected-ranking-artifacts.json"),
    )
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY"))
    args = parser.parse_args(argv)

    token = os.environ.get("GH_TOKEN")
    if not token:
        print("GH_TOKEN is required", file=sys.stderr)
        return 2
    if not args.repository:
        print("--repository or GITHUB_REPOSITORY is required", file=sys.stderr)
        return 2

    try:
        artifacts = list_recent_ranking_artifacts(
            args.repository,
            token,
            limit=args.limit,
        )
        download_ranking_history(artifacts, token, args.out)
        args.selection_out.write_text(
            json.dumps(artifacts, indent=2) + "\n",
            encoding="utf-8",
        )
    except (HTTPError, URLError, OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(f"Collected {len(artifacts)} ranking diff reports.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
