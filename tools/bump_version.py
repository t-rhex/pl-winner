"""Bump pyproject.toml version and roll the CHANGELOG Unreleased section.

Usage:
    python tools/bump_version.py patch      # 0.2.0 -> 0.2.1
    python tools/bump_version.py minor      # 0.2.0 -> 0.3.0
    python tools/bump_version.py major      # 0.2.0 -> 1.0.0
    python tools/bump_version.py 0.4.2      # explicit version

Idempotent w.r.t. CHANGELOG: only renames the Unreleased section; if there's
no [Unreleased] section it inserts a new entry above the previous version.
"""
from __future__ import annotations

import datetime as dt
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"
CHANGELOG = ROOT / "CHANGELOG.md"
INIT = ROOT / "src" / "__init__.py"
HTTP_UTILS = ROOT / "src" / "http_utils.py"


VERSION_RE = re.compile(r'^version\s*=\s*"([^"]+)"', re.MULTILINE)


def read_current_version() -> str:
    text = PYPROJECT.read_text()
    m = VERSION_RE.search(text)
    if not m:
        raise SystemExit("Could not find version in pyproject.toml")
    return m.group(1)


def parse(v: str) -> tuple[int, int, int]:
    parts = v.split(".")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        raise SystemExit(f"Not a valid X.Y.Z version: {v!r}")
    return tuple(int(p) for p in parts)  # type: ignore[return-value]


def bump(current: str, kind: str) -> str:
    if re.fullmatch(r"\d+\.\d+\.\d+", kind):
        return kind
    major, minor, patch = parse(current)
    if kind == "major":
        return f"{major + 1}.0.0"
    if kind == "minor":
        return f"{major}.{minor + 1}.0"
    if kind == "patch":
        return f"{major}.{minor}.{patch + 1}"
    raise SystemExit(f"Unknown bump kind: {kind!r} (expected patch|minor|major or X.Y.Z)")


def update_pyproject(new_version: str) -> None:
    text = PYPROJECT.read_text()
    new = VERSION_RE.sub(f'version = "{new_version}"', text, count=1)
    PYPROJECT.write_text(new)


def update_init(new_version: str) -> None:
    if not INIT.exists():
        return
    text = INIT.read_text()
    new = re.sub(
        r'__version__\s*=\s*"[^"]+"',
        f'__version__ = "{new_version}"',
        text,
        count=1,
    )
    INIT.write_text(new)


def update_user_agent(new_version: str) -> None:
    if not HTTP_UTILS.exists():
        return
    text = HTTP_UTILS.read_text()
    new = re.sub(
        r'USER_AGENT\s*=\s*"pl-winner/[\d.]+',
        f'USER_AGENT = "pl-winner/{new_version}',
        text,
        count=1,
    )
    HTTP_UTILS.write_text(new)


def update_changelog(new_version: str, today: str) -> None:
    text = CHANGELOG.read_text()
    new_section_header = f"## [{new_version}] — {today}"

    if "## [Unreleased]" in text:
        # Replace the Unreleased header in-place AND add a fresh Unreleased above it.
        text = text.replace(
            "## [Unreleased]",
            f"## [Unreleased]\n\n{new_section_header}",
            1,
        )
    else:
        # No Unreleased section — inject above the most recent version heading
        text = re.sub(
            r"(^## \[)",
            f"## [Unreleased]\n\n{new_section_header}\n\n\\1",
            text,
            count=1,
            flags=re.MULTILINE,
        )

    # Update / append the link references at the bottom.
    text = _update_compare_links(text, new_version)
    CHANGELOG.write_text(text)


def _update_compare_links(text: str, new_version: str) -> str:
    repo_url = "https://github.com/t-rhex/pl-winner"
    # Find the previous version header (the next "## [X.Y.Z]" after Unreleased)
    versions = re.findall(r"^## \[(\d+\.\d+\.\d+)\]", text, flags=re.MULTILINE)
    if not versions:
        return text

    # Replace the [Unreleased] link target to compare from the new version
    text = re.sub(
        r"\[Unreleased\]:\s*.+",
        f"[Unreleased]: {repo_url}/compare/v{new_version}...HEAD",
        text,
    )
    # Insert a link line for the new version right after the [Unreleased] line if missing
    new_link = f"[{new_version}]: {repo_url}/releases/tag/v{new_version}"
    if new_link not in text:
        text = re.sub(
            r"(\[Unreleased\]:.+\n)",
            f"\\1{new_link}\n",
            text,
            count=1,
        )
    return text


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    kind = sys.argv[1]
    current = read_current_version()
    new_version = bump(current, kind)
    today = dt.date.today().isoformat()

    update_pyproject(new_version)
    update_init(new_version)
    update_user_agent(new_version)
    update_changelog(new_version, today)

    print(f"{current} -> {new_version}")
    print("   pyproject.toml   updated")
    print("   src/__init__.py  updated")
    print("   src/http_utils.py updated")
    print(f"   CHANGELOG.md     updated ([{new_version}] section, dated {today})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
