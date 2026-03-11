#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT_PATH = ROOT / "pyproject.toml"
FORMULA_PATH = ROOT / "Formula" / "nanobot.rb"
DIST_DIR = ROOT / "dist"
TAP_NAME = "nanobot/local"
FORMULA_NAME = "nanobot"


def project_version() -> str:
    data = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))
    return str(data["project"]["version"])


def build_sdist() -> Path:
    subprocess.run(["uv", "build", "--sdist"], cwd=ROOT, check=True)
    version = project_version().replace("-", "_")
    return DIST_DIR / f"nanobot_ai-{version}.tar.gz"


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def patch_formula_source(formula_text: str, sdist_path: Path) -> str:
    url = f"file://{sdist_path.resolve()}"
    sha256 = file_sha256(sdist_path)
    updated = re.sub(r'^  url ".*"$', f'  url "{url}"', formula_text, count=1, flags=re.MULTILINE)
    updated = re.sub(
        r'^  sha256 ".*"$',
        f'  sha256 "{sha256}"',
        updated,
        count=1,
        flags=re.MULTILINE,
    )
    return updated


def ensure_tap(tap_name: str) -> Path:
    taps = subprocess.run(
        ["brew", "tap"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.splitlines()
    if tap_name not in taps:
        subprocess.run(["brew", "tap-new", "--no-git", tap_name], cwd=ROOT, check=True)

    repo = subprocess.run(
        ["brew", "--repository", tap_name],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return Path(repo.stdout.strip())


def install_formula(formula_ref: str) -> str:
    installed = subprocess.run(
        ["brew", "list", "--versions", FORMULA_NAME],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    command = ["brew", "reinstall" if installed.returncode == 0 else "install", formula_ref]
    subprocess.run(command, cwd=ROOT, check=True)
    return command[1]


def manage_service(mode: str | None) -> None:
    if mode is None:
        return
    subprocess.run(["brew", "services", mode, FORMULA_NAME], cwd=ROOT, check=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Install or refresh the Homebrew nanobot formula from this clone."
    )
    parser.add_argument(
        "--tap",
        default=TAP_NAME,
        help=f"Homebrew tap name to use for the local formula (default: {TAP_NAME})",
    )
    parser.add_argument(
        "--service",
        choices=["start", "restart"],
        help="Optionally start or restart the Homebrew-managed nanobot service after install",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    sdist_path = build_sdist()
    if not sdist_path.exists():
        raise RuntimeError(f"Expected source distribution at {sdist_path}")

    tap_repo = ensure_tap(args.tap)
    tap_formula_path = tap_repo / "Formula" / FORMULA_PATH.name
    tap_formula_path.parent.mkdir(parents=True, exist_ok=True)

    formula_text = FORMULA_PATH.read_text(encoding="utf-8")
    tap_formula_path.write_text(patch_formula_source(formula_text, sdist_path), encoding="utf-8")

    action = install_formula(f"{args.tap}/{FORMULA_NAME}")
    manage_service(args.service)

    print(f"Built {sdist_path}")
    print(f"Updated {tap_formula_path}")
    print(f"brew {action} {args.tap}/{FORMULA_NAME}")
    if args.service:
        print(f"brew services {args.service} {FORMULA_NAME}")


if __name__ == "__main__":
    main()
