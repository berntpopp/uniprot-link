"""Deploy contract: the deployed npm overlay declares a numeric user; the release
Compose files must not, because the shared release gate forbids it there.

Research use only; not clinical decision support.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]  # tests/unit/<file> -> repo root
NPM_COMPOSE = ROOT / "docker" / "docker-compose.npm.yml"
RELEASE_MANIFEST = ROOT / "container-release.json"

NUMERIC_USER = re.compile(r"^[1-9][0-9]*:[1-9][0-9]*$")


class _TolerantSafeLoader(yaml.SafeLoader):
    """A SafeLoader that tolerates Compose's custom tags (``!reset``, ``!override``).

    The release Compose files use these tags to reset/replace list fields across
    overlays; plain ``yaml.safe_load`` cannot construct them and raises.
    """


_TolerantSafeLoader.add_multi_constructor(
    "!",
    lambda loader, suffix, node: (
        loader.construct_scalar(node) if isinstance(node, yaml.ScalarNode) else None
    ),
)


def _load(path: Path) -> dict:
    # S506: _TolerantSafeLoader subclasses SafeLoader and only adds a multi-constructor
    # that returns a plain scalar/None for Compose's "!"-prefixed tags -- it never gains
    # the unsafe object-instantiation constructors ruff is warning about.
    return yaml.load(path.read_text(encoding="utf-8"), Loader=_TolerantSafeLoader)  # noqa: S506


def test_npm_overlay_declares_numeric_user_for_every_service() -> None:
    """The deployed overlay declares a numeric non-root user for every service.

    The fleet controller (strato_v6_docker_npm, scripts/utils/deployment_preflight.py)
    accepts a declared user only as numeric non-root, and its runtime observer proves
    the effective uid from /proc -- a name like the image's ``USER app`` is rejected.
    """
    compose = _load(NPM_COMPOSE)
    for name, service in compose["services"].items():
        user = service.get("user")
        assert isinstance(user, str) and NUMERIC_USER.match(user), (
            f"{name} declares user={user!r} in docker/docker-compose.npm.yml; the "
            "fleet controller requires a numeric 'uid:gid' non-root user"
        )


def test_release_compose_files_never_declare_a_user() -> None:
    """The release Compose files must not declare `user`; the shared release gate forbids it.

    `container_release.py validate-compose` rejects `user` on the application service
    of the Compose files named in `container-release.json` -- the exact opposite of
    what the deployment controller requires of the npm overlay above. The numeric user
    therefore lives only in docker/docker-compose.npm.yml.
    """
    manifest = json.loads(RELEASE_MANIFEST.read_text(encoding="utf-8"))
    for rel_path in manifest["service"]["compose_files"]:
        compose = _load(ROOT / rel_path)
        for name, service in compose["services"].items():
            assert "user" not in service, (
                f"{name} in {rel_path} declares 'user'; {rel_path} is part of the "
                "release stack (container-release.json) and the shared release gate "
                "forbids 'user' there"
            )
