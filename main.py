"""Select and start the configured chat-platform backend."""

from __future__ import annotations

from dotenv import load_dotenv

from backend_config import Backend, get_backend


def main() -> None:
    load_dotenv()
    backend = get_backend()

    if backend is Backend.TELEGRAM:
        # telegram_bot currently owns Telegram handler registration and startup.
        import telegram_bot  # noqa: F401

        return

    raise SystemExit(
        "The Discord backend is not available yet. Set BOT_BACKEND=telegram "
        "to start the current backend."
    )


if __name__ == "__main__":
    main()
