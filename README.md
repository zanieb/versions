# Astral Versions Repository

Tracks release metadata for Astral products.


## Format

Release metadata is stored in versioned ndjson files:

- `v1/` - Version
  - `<name>.ndjson` - Release metadata

Each line in the NDJSON files represents one release, e.g.:

```json
{
  "version": "0.8.3",
  "date": "2025-07-29T16:45:46.646976+00:00",
  "artifacts": [
    {
      "platform": "aarch64-apple-darwin",
      "url": "https://github.com/astral-sh/uv/releases/download/0.8.3/uv-aarch64-apple-darwin.tar.gz",
      "sha256_url": "https://github.com/astral-sh/uv/releases/download/0.8.3/uv-aarch64-apple-darwin.tar.gz.sha256",
      "archive_format": "tar.gz"
    }
  ]
}
```

## Usage

### Publishing a new version

The publish script consumes a plan from `cargo-dist`:

```bash
cargo dist plan --output-format=json | uv run scripts/publish-version.py
```

### Backfilling historical versions

There's a backfill utility which pulls releases and artifacts from GitHub:

```bash
uv run scripts/backfill-versions.py <name>
```
