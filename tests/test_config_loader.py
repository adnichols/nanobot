"""Tests for config loading compatibility behavior."""

from __future__ import annotations

import json

from nanobot.config.loader import load_config


def test_load_config_ignores_unknown_keys_and_keeps_known_values(tmp_path, capsys):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "agents": {
                    "defaults": {
                        "provider": "synthetic",
                    }
                },
                "providers": {
                    "synthetic": {
                        "apiKey": "syn_test_key",
                    }
                },
                "channels": {
                    "telegram": {
                        "enabled": True,
                        "token": "telegram-token",
                    }
                },
                "futureSection": {
                    "enabled": True,
                },
            }
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.agents.defaults.provider == "synthetic"
    assert config.providers.synthetic.api_key == "syn_test_key"
    assert config.channels.telegram.enabled is True
    assert config.channels.telegram.token == "telegram-token"

    captured = capsys.readouterr()
    assert "Ignoring unknown config keys" in captured.out
    assert "futureSection" in captured.out


def test_load_config_falls_back_to_defaults_for_invalid_known_values(tmp_path, capsys):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "gateway": {
                    "port": "not-a-port",
                }
            }
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.gateway.port == 18790

    captured = capsys.readouterr()
    assert "Failed to load config" in captured.out
    assert "Using default configuration." in captured.out
