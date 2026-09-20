"""Environment-driven configuration. Secrets stay in the environment (or the gitignored backend/.env)."""
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent

SERVER_NAME = "brain-assistant"
SERVER_VERSION = "0.1.0"

_TRUE = {"1", "true", "yes", "on"}
_DEV_ENVS = {"development", "dev", "test"}
DEFAULT_DEV_ACTOR = "claude-code-dev"


class ConfigError(RuntimeError):
    """Raised at startup when the configuration is unsafe; the message is safe to print."""


@dataclass(frozen=True)
class Config:
    env: str
    allow_writes: bool
    actor: str
    write_rate_per_minute: int

    @property
    def is_development(self) -> bool:
        return self.env in _DEV_ENVS


def _flag(env: Mapping[str, str], name: str) -> bool:
    return env.get(name, "").strip().lower() in _TRUE


def load_config(env: Mapping[str, str] | None = None) -> Config:
    """Builds the config and refuses unsafe combinations.

    The application has no authentication, so the only identity available is a *development* one.
    It must never activate silently in production: outside development/test the server refuses to
    start unless BRAIN_MCP_ALLOW_PRODUCTION=true AND BRAIN_MCP_ACTOR is set explicitly.
    """
    source = os.environ if env is None else env
    name = source.get("BRAIN_ENV", "").strip().lower() or "development"
    is_dev = name in _DEV_ENVS
    actor = source.get("BRAIN_MCP_ACTOR", "").strip()

    if not is_dev:
        if not _flag(source, "BRAIN_MCP_ALLOW_PRODUCTION"):
            raise ConfigError(
                f"BRAIN_ENV={name!r} is not a development environment; refusing to start. "
                "Set BRAIN_MCP_ALLOW_PRODUCTION=true to override explicitly."
            )
        if not actor:
            raise ConfigError("BRAIN_MCP_ACTOR must be set explicitly outside development.")
    elif not actor:
        actor = DEFAULT_DEV_ACTOR

    try:
        rate = int(source.get("BRAIN_MCP_WRITE_RATE_PER_MINUTE", "30"))
    except ValueError as exc:
        raise ConfigError("BRAIN_MCP_WRITE_RATE_PER_MINUTE must be an integer.") from exc
    if rate < 1:
        raise ConfigError("BRAIN_MCP_WRITE_RATE_PER_MINUTE must be >= 1.")

    return Config(
        env=name,
        allow_writes=_flag(source, "BRAIN_MCP_ALLOW_WRITES"),
        actor=actor,
        write_rate_per_minute=rate,
    )
