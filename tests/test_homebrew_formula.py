from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parent.parent / "scripts" / "update_homebrew_formula.py"
SPEC = importlib.util.spec_from_file_location("update_homebrew_formula", MODULE_PATH)
assert SPEC is not None
assert SPEC.loader is not None
brew_formula = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = brew_formula
SPEC.loader.exec_module(brew_formula)


def test_normalize_version_strips_tag_prefix():
    assert brew_formula.normalize_version("v0.1.4.post3") == "0.1.4.post3"
    assert brew_formula.normalize_version("0.1.4.post3") == "0.1.4.post3"


def test_project_version_reads_pyproject(tmp_path):
    pyproject_path = tmp_path / "pyproject.toml"
    pyproject_path.write_text(
        '[project]\nname = "nanobot-ai"\nversion = "1.2.3"\n',
        encoding="utf-8",
    )

    assert brew_formula.project_version(pyproject_path) == "1.2.3"


def test_select_sdist_returns_expected_artifact():
    payload = {
        "urls": [
            {
                "packagetype": "bdist_wheel",
                "url": "https://example.invalid/nanobot.whl",
                "digests": {"sha256": "ignored"},
            },
            {
                "packagetype": "sdist",
                "url": "https://files.pythonhosted.org/packages/source/n/nanobot-ai/nanobot-ai-1.2.3.tar.gz",
                "digests": {"sha256": "abc123"},
            },
        ]
    }

    artifact = brew_formula.select_sdist(payload, "1.2.3")

    assert artifact.version == "1.2.3"
    assert artifact.url.endswith("nanobot-ai-1.2.3.tar.gz")
    assert artifact.sha256 == "abc123"


def test_render_formula_includes_service_and_upgrade_guidance():
    source = brew_formula.SourceArtifact(
        version="1.2.3",
        url="https://files.pythonhosted.org/packages/source/n/nanobot-ai/nanobot-ai-1.2.3.tar.gz",
        sha256="abc123",
    )

    formula = brew_formula.render_formula(
        source,
        'resource "click" do\n    url "https://files.pythonhosted.org/packages/source/c/click/click-8.3.1.tar.gz"\n    sha256 "deadbeef"\n  end',
    )

    assert (
        'url "https://files.pythonhosted.org/packages/source/n/nanobot-ai/nanobot-ai-1.2.3.tar.gz"'
        in formula
    )
    assert 'sha256 "abc123"' in formula
    assert 'depends_on "libyaml"' in formula
    assert 'resource "click" do' in formula
    assert (
        '    url "https://files.pythonhosted.org/packages/source/c/click/click-8.3.1.tar.gz"'
        in formula
    )
    assert "service do" in formula
    assert 'run [opt_bin/"nanobot", "gateway"]' in formula
    assert "brew update && brew upgrade nanobot" in formula
    assert "restart_service: :changed" in formula


def test_filter_resource_block_excludes_hf_xet_only():
    resource_block = (
        'resource "click" do\n'
        '  url "https://example.invalid/click.tar.gz"\n'
        '  sha256 "aaa"\n'
        "end\n\n"
        'resource "hf-xet" do\n'
        '  url "https://example.invalid/hf-xet.tar.gz"\n'
        '  sha256 "bbb"\n'
        "end\n"
    )

    filtered = brew_formula.filter_resource_block(resource_block)

    assert 'resource "click" do' in filtered
    assert 'resource "hf-xet" do' not in filtered


def test_ensure_required_resources_appends_missing_lock_resource(monkeypatch):
    monkeypatch.setattr(
        brew_formula,
        "lock_packages",
        lambda: {
            "agent-client-protocol": {
                "sdist": {
                    "url": "https://files.pythonhosted.org/packages/source/a/agent_client_protocol/agent_client_protocol-0.8.1.tar.gz",
                    "hash": "sha256:abc123",
                }
            }
        },
    )

    ensured = brew_formula.ensure_required_resources(
        'resource "click" do\n  url "https://example.invalid/click.tar.gz"\n  sha256 "aaa"\nend',
        {"agent-client-protocol"},
    )

    assert 'resource "click" do' in ensured
    assert 'resource "agent-client-protocol" do' in ensured
    assert 'sha256 "abc123"' in ensured
