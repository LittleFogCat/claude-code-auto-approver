"""Unit tests for settings loader."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from classifier.settings import AuthConfig, Settings, _deep_merge, anthropic_api_key


def test_deep_merge_simple():
    base = {"a": 1, "b": {"c": 2}}
    overlay = {"b": {"d": 3}}
    out = _deep_merge(base, overlay)
    assert out == {"a": 1, "b": {"c": 2, "d": 3}}


def test_deep_merge_overlay_wins():
    base = {"a": 1, "b": 2}
    overlay = {"b": 3}
    assert _deep_merge(base, overlay) == {"a": 1, "b": 3}


def test_deep_merge_adds_keys():
    base = {"a": 1}
    overlay = {"b": 2}
    assert _deep_merge(base, overlay) == {"a": 1, "b": 2}


def test_settings_load_defaults(tmp_path, monkeypatch):
    # Make sure we don't accidentally read user's real config
    monkeypatch.setattr("classifier.settings._user_rules_yaml", lambda: {})
    monkeypatch.setattr("classifier.settings._bundled_default_yaml", lambda: {})
    s = Settings.load()
    assert s.service.host == "127.0.0.1"
    assert s.service.port == 8765
    assert s.behavior.fail_open_on_error is True


def test_settings_env_override(monkeypatch):
    monkeypatch.setattr("classifier.settings._user_rules_yaml", lambda: {})
    monkeypatch.setattr("classifier.settings._bundled_default_yaml", lambda: {})
    monkeypatch.setenv("CLF_SERVICE_PORT", "9999")
    monkeypatch.setenv("CLF_BEHAVIOR_FAIL_OPEN_ON_ERROR", "false")
    s = Settings.load()
    assert s.service.port == 9999
    assert s.behavior.fail_open_on_error is False


def test_anthropic_api_key_reads_env(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-123")
    assert anthropic_api_key() == "sk-test-123"


def test_anthropic_api_key_missing(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert anthropic_api_key() is None