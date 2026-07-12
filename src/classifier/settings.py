"""Settings loader with YAML + env-var overlay.

Precedence (later wins):
  1. Built-in defaults
  2. config/default.yaml (bundled)
  3. ~/.config/clf/rules.yaml (user main config)
  4. Environment variables (CLF_*)

ANTHROPIC_API_KEY is intentionally read directly from env, not from YAML,
to keep secrets out of config files.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


DEFAULTS: dict[str, Any] = {
    "service": {
        "host": "127.0.0.1",
        "port": 8765,
    },
    "auth": {
        "bridge_token": "",
    },
    "behavior": {
        "fail_open_on_error": True,
        "enable_claude_fallback": True,
        "claude_model": "claude-haiku-4-5",
        "claude_timeout_s": 8,
    },
    "logging": {
        "level": "INFO",
        "file": "logs/decisions.jsonl",
    },
}


def _bundled_default_yaml() -> dict[str, Any]:
    """Load config/default.yaml if present, else return {}."""
    p = Path(__file__).resolve().parents[2] / "config" / "default.yaml"
    if not p.exists():
        return {}
    with p.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data if isinstance(data, dict) else {}


def _user_rules_yaml() -> dict[str, Any]:
    """Load user rules.yaml.

    Honors ``CLF_RULES_FILE`` env var (useful for testing / per-project configs);
    falls back to ``~/.config/clf/rules.yaml``.
    """
    p_str = os.environ.get("CLF_RULES_FILE")
    if p_str:
        p = Path(p_str)
    else:
        p = Path.home() / ".config" / "clf" / "rules.yaml"
    if not p.exists():
        return {}
    with p.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data if isinstance(data, dict) else {}


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge overlay into base. Overlay wins."""
    out = dict(base)
    for k, v in overlay.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


class RuleSpec(BaseModel):
    """Spec loaded from YAML for a single rule."""

    model_config = ConfigDict(extra="forbid")

    id: str
    type: str
    priority: int = 50
    severity: str = "medium"
    enabled: bool = True
    pattern: str | None = None
    flags: int = 0
    paths: list[str] = Field(default_factory=list)
    decision_suggestion: str | None = None
    reason: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class ServiceConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8765


class AuthConfig(BaseModel):
    bridge_token: str = ""


class BehaviorConfig(BaseModel):
    fail_open_on_error: bool = True
    enable_claude_fallback: bool = True
    claude_model: str = "claude-haiku-4-5"
    claude_timeout_s: int = 8


class LoggingConfig(BaseModel):
    level: str = "INFO"
    file: str = "logs/decisions.jsonl"


class RulesConfig(BaseModel):
    rules: list[RuleSpec] = Field(default_factory=list)


def _env_overrides(section: str) -> dict[str, Any]:
    """Read CLF_<SECTION>_<KEY> env vars and return a dict for that section."""
    prefix = f"CLF_{section.upper()}_"
    out: dict[str, Any] = {}
    for k, v in os.environ.items():
        if k.startswith(prefix):
            short = k[len(prefix):].lower()
            out[short] = v
    return out


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CLF_",
        env_nested_delimiter="__",
        case_sensitive=False,
        extra="ignore",
    )

    service: ServiceConfig = Field(default_factory=ServiceConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    behavior: BehaviorConfig = Field(default_factory=BehaviorConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    rules: RulesConfig = Field(default_factory=RulesConfig)

    @classmethod
    def load(cls) -> "Settings":
        """Load YAML overlays + env vars.

        Precedence (later wins): DEFAULTS < default.yaml < user rules.yaml < env vars.
        """
        merged = dict(DEFAULTS)
        merged = _deep_merge(merged, _bundled_default_yaml())
        merged = _deep_merge(merged, _user_rules_yaml())

        # Overlay env vars on top of merged yaml values
        for section in ("service", "auth", "behavior", "logging"):
            if section in merged:
                merged[section] = {**merged[section], **_env_overrides(section)}

        kwargs: dict[str, Any] = {}
        if "service" in merged:
            kwargs["service"] = ServiceConfig(**merged["service"])
        if "auth" in merged:
            kwargs["auth"] = AuthConfig(**merged["auth"])
        if "behavior" in merged:
            kwargs["behavior"] = BehaviorConfig(**merged["behavior"])
        if "logging" in merged:
            kwargs["logging"] = LoggingConfig(**merged["logging"])
        rules_raw = merged.get("rules")
        # Accept either shape:
        #   rules: [ {...}, {...} ]                # top-level list
        #   rules: { rules: [ ... ] }              # nested (our internal default)
        if isinstance(rules_raw, list):
            rules_list = rules_raw
        elif isinstance(rules_raw, dict):
            rules_list = rules_raw.get("rules", []) or []
        else:
            rules_list = []
        if rules_list:
            kwargs["rules"] = RulesConfig(rules=[RuleSpec(**r) for r in rules_list])

        return cls(**kwargs)


def anthropic_api_key() -> str | None:
    """Read the Anthropic API key directly from the environment."""
    return os.environ.get("ANTHROPIC_API_KEY") or None