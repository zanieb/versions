#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx"]
# ///
"""Backfill historical versions from GitHub releases to NDJSON format.

Usage:
    # Backfill versions for a project (default: writes to ../v1/)
    backfill-versions.py <project-name>

    # Specify custom GitHub org/repo
    backfill-versions.py <project-name> --github astral-sh/uv

    # Specify custom output directory
    backfill-versions.py <project-name> --output <path>
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, TypedDict

import httpx


class Artifact(TypedDict):
    platform: str
    url: str
    sha256_url: str
    archive_format: str


class Version(TypedDict):
    version: str
    date: str
    artifacts: list[Artifact]


class VersionsFile(TypedDict):
    versions: list[Version]


def get_archive_format(filename: str) -> str:
    """Determine archive format from filename."""
    if filename.endswith(".tar.gz"):
        return "tar.gz"
    elif filename.endswith(".zip"):
        return "zip"
    else:
        return "unknown"


def extract_platform_from_filename(filename: str, project_name: str) -> str | None:
    """Extract platform target triple from filename."""
    # Pattern: {project}-{platform}.{ext}
    pattern = rf"^{re.escape(project_name)}-(.+?)\.(tar\.gz|zip)$"
    match = re.match(pattern, filename)
    if match:
        return match.group(1)
    return None


def fetch_github_releases(
    org: str, repo: str, per_page: int = 100
) -> list[dict[str, Any]]:
    """Fetch all releases from GitHub API."""
    releases = []
    page = 1

    # Build headers with GitHub token if available
    headers = {"Accept": "application/vnd.github.v3+json"}
    github_token = os.environ.get("GITHUB_TOKEN")
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"
        print("Using GITHUB_TOKEN for authentication", file=sys.stderr)
    else:
        print(
            "No GITHUB_TOKEN found, using unauthenticated requests (may hit rate limits)",
            file=sys.stderr,
        )

    with httpx.Client() as client:
        while True:
            print(f"Fetching page {page}...", file=sys.stderr)
            response = client.get(
                f"https://api.github.com/repos/{org}/{repo}/releases",
                params={"per_page": per_page, "page": page},
                headers=headers,
            )
            response.raise_for_status()

            data = response.json()
            if not data:
                break

            releases.extend(data)
            page += 1

    return releases


def process_release(
    release: dict[str, Any], project_name: str, org: str, repo: str
) -> Version | None:
    """Process a GitHub release into our version format."""
    # Skip pre-releases and drafts
    if release.get("prerelease") or release.get("draft"):
        return None

    tag_name = release.get("tag_name", "")
    published_at = release.get("published_at", "")
    assets = release.get("assets", [])

    # Skip if no tag or date
    if not tag_name or not published_at:
        return None

    artifacts: list[Artifact] = []

    for asset in assets:
        name = asset.get("name", "")
        browser_download_url = asset.get("browser_download_url", "")

        # Skip non-binary assets
        if not name.startswith(f"{project_name}-") or not (
            name.endswith(".tar.gz") or name.endswith(".zip")
        ):
            continue

        # Skip checksum files
        if name.endswith(".sha256"):
            continue

        platform = extract_platform_from_filename(name, project_name)
        if not platform:
            continue

        # Use the actual download URL from GitHub API
        artifact: Artifact = {
            "platform": platform,
            "url": browser_download_url,
            "sha256_url": f"{browser_download_url}.sha256",
            "archive_format": get_archive_format(name),
        }
        artifacts.append(artifact)

    # Skip releases without artifacts
    if not artifacts:
        return None

    # Sort artifacts by platform for consistency
    artifacts.sort(key=lambda x: x["platform"])

    return {
        "version": tag_name,
        "date": published_at,
        "artifacts": artifacts,
    }


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Backfill historical versions from GitHub releases"
    )
    parser.add_argument("project_name", help="Project name (e.g., 'uv', 'ruff')")
    parser.add_argument(
        "--github",
        help="GitHub org/repo (default: astral-sh/{project_name})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Output directory (default: ../v1/ relative to this script)",
    )
    args = parser.parse_args()

    project_name = args.project_name

    # Calculate the output directory
    if args.output:
        versions_repo = args.output
    else:
        # Default: script is in versions/scripts/, output to versions/v1/
        script_dir = Path(__file__).parent
        versions_repo = script_dir.parent / "v1"

    # Ensure versions directory exists
    versions_repo.mkdir(parents=True, exist_ok=True)

    # Parse GitHub org/repo
    if args.github:
        org_repo = args.github
        if "/" not in org_repo:
            print("Error: --github must be in format 'org/repo'", file=sys.stderr)
            sys.exit(1)
        org, repo = org_repo.split("/", 1)
    else:
        # Default to astral-sh/{project_name}
        org = "astral-sh"
        repo = project_name

    versions_file = versions_repo / f"{project_name}.ndjson"

    # Fetch all releases
    print(f"Fetching releases from GitHub {org}/{repo}...", file=sys.stderr)
    releases = fetch_github_releases(org, repo)
    print(f"Found {len(releases)} releases", file=sys.stderr)

    # Process releases
    versions: list[Version] = []
    for release in releases:
        version = process_release(release, project_name, org, repo)
        if version:
            print(f"Processed version: {version['version']}", file=sys.stderr)
            versions.append(version)

    # Sort by date (newest first)
    versions.sort(key=lambda v: v["date"], reverse=True)

    print(f"Processed {len(versions)} valid versions", file=sys.stderr)

    # Ensure parent directory exists
    versions_file.parent.mkdir(parents=True, exist_ok=True)

    # Write to file in NDJSON format
    print(f"Writing to {versions_file}...", file=sys.stderr)
    with open(versions_file, "w") as f:
        # Write each version as a separate line
        for version in versions:
            f.write(json.dumps(version, separators=(",", ":")) + "\n")

    print("Done!", file=sys.stderr)


if __name__ == "__main__":
    main()
