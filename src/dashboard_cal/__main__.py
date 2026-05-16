"""``python -m dashboard_cal`` / ``dashboard-cal`` entry point."""

from __future__ import annotations

import argparse
import sys

from . import app


def main() -> int:
    parser = argparse.ArgumentParser(prog="dashboard-cal", description=__doc__)
    parser.add_argument(
        "--reauth",
        action="store_true",
        help="Force a new Google OAuth consent (clears the cached token).",
    )
    args = parser.parse_args()
    try:
        app.run(force_reauth=args.reauth)
    except FileNotFoundError as e:
        # ``FileNotFoundError`` here is the user-facing "config.yaml not
        # found at <path>; copy config.example.yaml" message from
        # ``load_settings``. It's explicit guidance, no secret content.
        print(str(e), file=sys.stderr)
        return 2
    except Exception as e:
        # Top-level safety net. Print only the exception class so we don't
        # leak the underlying message (which may carry HTTP response bodies,
        # OAuth metadata, or filesystem paths from chained tracebacks).
        # Details are still available via the application log.
        print(f"dashboard-cal: failed to start ({type(e).__name__})", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
