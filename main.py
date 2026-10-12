"""Select and start the configured chat-platform backend."""

from __future__ import annotations

from dotenv import load_dotenv

from backend_config import Backend, get_backend


def main() -> None:
    load_dotenv()
    backend = get_backend()

    if backend is Backend.TELEGRAM:
        from telegram_bot import run

        run()
        return

    from discord_bot import run

    run()


if __name__ == "__main__":
    main()
