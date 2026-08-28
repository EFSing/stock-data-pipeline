"""Run the Phase 5K-B1-A IBKR readiness-only preflight."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from research.phase5k_b1a_ibkr_readiness import (
    CAPTURE_MODE,
    DEFAULT_MANIFEST_PATH,
    ConnectionConfig,
    FROZEN_STATUS,
    FREEZE_ARTIFACT_NOT_ACQUIRED_STATUS,
    OfficialIbapiSession,
    ReadinessError,
    run_readiness,
    VALIDATE_EXISTING_MODE,
    validate_existing_manifest,
    write_manifest,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=(CAPTURE_MODE, VALIDATE_EXISTING_MODE),
        required=True,
        help="capture live readiness, or validate an already saved capture",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_MANIFEST_PATH)
    args = parser.parse_args(argv)

    if args.mode == VALIDATE_EXISTING_MODE:
        try:
            validate_existing_manifest(args.output)
        except ReadinessError as exc:
            print(exc.status)
            return 2
        except Exception:
            # A tampered or structurally malformed saved file is a freeze
            # artifact failure, never a live-provider result.
            print(FREEZE_ARTIFACT_NOT_ACQUIRED_STATUS)
            return 2
        print(FROZEN_STATUS)
        return 0

    try:
        config = ConnectionConfig.from_env()
        with OfficialIbapiSession(config) as session:
            manifest = run_readiness(session)
        write_manifest(args.output, manifest)
    except ReadinessError as exc:
        print(exc.status)
        return 2
    except Exception:
        # Do not print provider exceptions: error messages can contain data
        # returned by a local trading application.  The process remains fail
        # closed and never writes a partial readiness artifact.
        print("US_PROVIDER_NOT_READY")
        return 2
    # Capture creates the candidate artifact.  It must never announce final
    # frozen success, even if a pin happens to exist from an earlier review.
    print(FREEZE_ARTIFACT_NOT_ACQUIRED_STATUS)
    return 2


if __name__ == "__main__":
    sys.exit(main())
