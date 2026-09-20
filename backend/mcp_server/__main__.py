"""Entry point: `python -m mcp_server`. stdout carries only MCP JSON-RPC; everything else goes to stderr."""
import logging
import sys
import threading

from dotenv import load_dotenv

from mcp_server.config import BACKEND_DIR, ConfigError, load_config
from mcp_server.errors import RedactingFilter


def _configure_logging() -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
    handler.addFilter(RedactingFilter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(logging.INFO)


def _warm_embeddings_in_background() -> None:
    """Loads the embedding model off the request path so the first search is not a 10s stall."""

    def warm() -> None:
        try:
            from app import embeddings

            embeddings.embed_text("warm-up")
        except Exception as exc:  # warm-up is best effort
            logging.getLogger("brain_mcp").warning("embedding warm-up failed: %s", type(exc).__name__)

    threading.Thread(target=warm, name="embedding-warmup", daemon=True).start()


def main() -> int:
    _configure_logging()
    # absolute path: works from any working directory; never overrides variables already in the environment
    load_dotenv(BACKEND_DIR / ".env")
    try:
        config = load_config()
    except ConfigError as exc:
        print(f"brain-assistant MCP: {exc}", file=sys.stderr)
        return 2

    from mcp_server.server import create_server

    logging.getLogger("brain_mcp").info("starting env=%s writes=%s", config.env, config.allow_writes)
    _warm_embeddings_in_background()
    create_server(config).run("stdio")
    return 0


if __name__ == "__main__":
    sys.exit(main())
