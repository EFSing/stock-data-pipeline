"""Run the Phase 5K-B1-A IBKR readiness-only preflight."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from research.phase5k_b1a_ibkr_readiness import (
    DEFAULT_MANIFEST_PATH,
    ConnectionConfig,
    FROZEN_STATUS,
    accept_frozen_manifest,
    OfficialIbapiSession,
    ReadinessError,
    run_readiness,
    write_manifest,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_MANIFEST_PATH)
    args = parser.parse_args(argv)
    try:
        config = ConnectionConfig.from_env()
        with OfficialIbapiSession(config) as session:
            manifest = run_readiness(session)
        write_manifest(args.output, manifest)
        accept_frozen_manifest(manifest)
    except ReadinessError as exc:
        print(exc.status)
        return 2
    except Exception:
        # Do not print provider exceptions: error messages can contain data
        # returned by a local trading application.  The process remains fail
        # closed and never writes a partial readiness artifact.
        print("US_PROVIDER_NOT_READY")
        return 2
    print(manifest["status"])
    return 0 if manifest["status"] == FROZEN_STATUS else 2


if __name__ == "__main__":
    sys.exit(main())
