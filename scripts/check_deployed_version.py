#!/usr/bin/env python3
"""Fail (exit 1) if the deployed server's version lags the source __version__.

Usage:
    python scripts/check_deployed_version.py [BASE_URL]
    # BASE_URL default: http://localhost:8000 ; reads /health.

A release is not "shipped" until this passes against the running endpoint.
"""

from __future__ import annotations

import json
import sys
import urllib.request

from uniprot_link import __version__


def main() -> int:
    base = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000").rstrip("/")
    try:
        with urllib.request.urlopen(f"{base}/health", timeout=10) as resp:  # noqa: S310
            health = json.load(resp)
    except Exception as exc:  # pragma: no cover - network failure path
        print(f"ERROR: could not reach {base}/health: {exc}", file=sys.stderr)
        return 2
    deployed = health.get("version")
    if deployed != __version__:
        print(
            f"STALE DEPLOYMENT: source __version__={__version__} "
            f"but {base} reports version={deployed} (git_sha={health.get('git_sha')}).",
            file=sys.stderr,
        )
        return 1
    print(f"OK: deployed version {deployed} matches source.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
