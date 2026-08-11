from __future__ import annotations

from vibe_stick.server.app import main


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
