from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parent.parent / "scripts" / "install_homebrew_from_clone.py"
SPEC = importlib.util.spec_from_file_location("install_homebrew_from_clone", MODULE_PATH)
assert SPEC is not None
assert SPEC.loader is not None
clone_install = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = clone_install
SPEC.loader.exec_module(clone_install)


def test_patch_formula_source_rewrites_url_and_sha(tmp_path):
    sdist_path = tmp_path / "nanobot_ai-0.1.4.post5.tar.gz"
    sdist_path.write_bytes(b"local release")

    formula_text = (
        "class Nanobot < Formula\n"
        '  url "https://example.invalid/nanobot.tar.gz"\n'
        '  sha256 "deadbeef"\n'
        "end\n"
    )

    patched = clone_install.patch_formula_source(formula_text, sdist_path)

    expected_sha = hashlib.sha256(b"local release").hexdigest()
    assert f'  url "file://{sdist_path.resolve()}"' in patched
    assert f'  sha256 "{expected_sha}"' in patched
    assert "https://example.invalid/nanobot.tar.gz" not in patched


def test_patch_formula_source_only_rewrites_first_url_and_sha(tmp_path):
    sdist_path = tmp_path / "nanobot_ai-0.1.4.post5.tar.gz"
    sdist_path.write_bytes(b"local release")

    formula_text = (
        "class Nanobot < Formula\n"
        '  url "https://example.invalid/nanobot.tar.gz"\n'
        '  sha256 "deadbeef"\n'
        '  resource "click" do\n'
        '    url "https://example.invalid/click.tar.gz"\n'
        '    sha256 "cafebabe"\n'
        "  end\n"
        "end\n"
    )

    patched = clone_install.patch_formula_source(formula_text, sdist_path)

    assert '    url "https://example.invalid/click.tar.gz"' in patched
    assert '    sha256 "cafebabe"' in patched
