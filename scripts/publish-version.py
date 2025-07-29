#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Update versions NDJSON file from cargo-dist manifest.

Usage:
    # Run cargo dist and update versions (default: writes to ../v1/)
    publish-versions.py

    # Pipe in manifest JSON
    cat manifest.json | publish-versions.py

    # Optionally specify custom output directory
    publish-versions.py --output <path>
"""

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypedDict


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


def run_cargo_dist_plan() -> dict[str, Any]:
    """Run cargo dist plan and return the manifest."""
    try:
        result = subprocess.run(
            ["cargo", "dist", "plan", "--output-format=json"],
            capture_output=True,
            text=True,
            check=True,
        )
        return json.loads(result.stdout)
    except subprocess.CalledProcessError as e:
        print(f"Error running cargo dist plan: {e}", file=sys.stderr)
        print(f"stderr: {e.stderr}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Error parsing cargo dist output: {e}", file=sys.stderr)
        sys.exit(1)


def extract_github_info(manifest: dict[str, Any]) -> tuple[str, str, str]:
    """Extract GitHub org, repo, and app name from manifest.

    Returns:
        Tuple of (github_org, github_repo, app_name)
    """
    # Find the first release to get app_name and artifacts
    app_name = None

    for release in manifest.get("releases", []):
        app_name = release["app_name"]
        # Look for a download URL in the announcement body to extract org/repo
        if "announcement_github_body" in manifest:
            # Extract from download URLs in the body
            match = re.search(
                r"https://github\.com/([^/]+)/([^/]+)/releases/download/",
                manifest["announcement_github_body"],
            )
            if match:
                return match.group(1), match.group(2), app_name
        break

    if app_name is None:
        raise ValueError("No releases found in manifest")

    # Fallback: assume astral-sh org
    return "astral-sh", app_name, app_name


def extract_version_info(manifest: dict[str, Any]) -> tuple[Version, str]:
    """Extract version information from cargo-dist manifest.

    Returns:
        Tuple of (Version dict, app_name)
    """
    version = manifest["announcement_tag"]
    github_org, github_repo, app_name = extract_github_info(manifest)
    artifacts_data = []

    # Get the artifacts for the release
    for release in manifest.get("releases", []):
        if release["app_name"] == app_name:
            # Process each artifact name from the list
            for artifact_name in release.get("artifacts", []):
                # Skip non-binary artifacts
                if (
                    not artifact_name.startswith(f"{app_name}-")
                    or artifact_name.endswith(".sha256")
                    or artifact_name == "source.tar.gz"
                    or artifact_name == "source.tar.gz.sha256"
                    or artifact_name == "sha256.sum"
                    or artifact_name.endswith(".sh")
                    or artifact_name.endswith(".ps1")
                ):
                    continue

                # Extract platform from filename (e.g., "uv-aarch64-apple-darwin.tar.gz")
                # Remove app name prefix and file extension
                prefix_len = len(app_name) + 1  # +1 for the dash
                if artifact_name.endswith(".tar.gz"):
                    platform = artifact_name[
                        prefix_len:-7
                    ]  # Remove prefix and ".tar.gz"
                elif artifact_name.endswith(".zip"):
                    platform = artifact_name[prefix_len:-4]  # Remove prefix and ".zip"
                else:
                    continue

                # Build artifact entry
                artifact: Artifact = {
                    "platform": platform,
                    "url": f"https://github.com/{github_org}/{github_repo}/releases/download/{version}/{artifact_name}",
                    "sha256_url": f"https://github.com/{github_org}/{github_repo}/releases/download/{version}/{artifact_name}.sha256",
                    "archive_format": get_archive_format(artifact_name),
                }
                artifacts_data.append(artifact)
            break

    # Sort artifacts by platform for consistency
    artifacts_data.sort(key=lambda x: x["platform"])

    version_info = {
        "version": version,
        "date": datetime.now(timezone.utc).isoformat(),
        "artifacts": artifacts_data,
    }

    return version_info, app_name


def update_versions_file(
    versions_path: Path, new_version: Version, max_versions: int = 100
) -> None:
    """Update the versions NDJSON file with a new version."""
    versions = []

    # Load existing versions if file exists
    if versions_path.exists():
        try:
            with open(versions_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        versions.append(json.loads(line))

        except (json.JSONDecodeError, KeyError) as e:
            print(
                f"Warning: Could not parse existing versions file: {e}", file=sys.stderr
            )
            versions = []

    # Check if version already exists
    existing_versions = {v["version"] for v in versions}
    if new_version["version"] in existing_versions:
        print(
            f"Version {new_version['version']} already exists, updating...",
            file=sys.stderr,
        )
        # Remove the existing version
        versions = [v for v in versions if v["version"] != new_version["version"]]

    # Add new version at the beginning
    versions.insert(0, new_version)

    # Keep only the most recent versions
    versions = versions[:max_versions]

    # Ensure parent directory exists
    versions_path.parent.mkdir(parents=True, exist_ok=True)

    # Write back to file in NDJSON format
    with open(versions_path, "w") as f:
        # Write each version as a separate line
        for version in versions:
            f.write(json.dumps(version, separators=(",", ":")) + "\n")


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Update product version files from cargo-dist manifest"
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Output directory (default: ../v1/ relative to this script)",
    )
    args = parser.parse_args()

    # Calculate the output directory
    if args.output:
        versions_repo = args.output
    else:
        # Default: script is in versions/scripts/, output to versions/v1/
        script_dir = Path(__file__).parent
        versions_repo = script_dir.parent / "v1"

    # Ensure versions directory exists
    versions_repo.mkdir(parents=True, exist_ok=True)

    # Get cargo dist manifest
    if sys.stdin.isatty():
        # No piped input, run cargo dist
        print("Running cargo dist plan...", file=sys.stderr)
        manifest = run_cargo_dist_plan()
    else:
        # Read from stdin
        print("Reading manifest from stdin...", file=sys.stderr)
        try:
            manifest = json.load(sys.stdin)
        except json.JSONDecodeError as e:
            print(f"Error parsing JSON from stdin: {e}", file=sys.stderr)
            sys.exit(1)

    # Extract version info and app name
    print("Extracting version information...", file=sys.stderr)
    version_info, app_name = extract_version_info(manifest)
    print(f"Found app: {app_name}", file=sys.stderr)
    print(f"Found version: {version_info['version']}", file=sys.stderr)
    print(f"Found {len(version_info['artifacts'])} artifacts", file=sys.stderr)

    # Determine versions file path based on app name
    versions_file = versions_repo / f"{app_name}.ndjson"

    # Update versions file
    print(f"Updating {versions_file}...", file=sys.stderr)
    update_versions_file(versions_file, version_info)

    print("Done!", file=sys.stderr)


if __name__ == "__main__":
    main()
