"""Run the one-time frozen strict-vs-cached semantic parity audit."""
from __future__ import annotations

import json
from pathlib import Path

from research.cache_semantic_parity import build_cache_semantic_parity_audit


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = PROJECT_ROOT / "artifacts" / "cache_semantic_parity"


def main() -> None:
    report = build_cache_semantic_parity_audit()
    output_dir = DEFAULT_OUTPUT
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "frozen_replay_cache_semantic_parity.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        "FROZEN_REPLAY_CACHE_SEMANTIC_PARITY_AUDIT "
        + json.dumps(report, ensure_ascii=False, sort_keys=True)
    )
    raise SystemExit(0 if report["status"] == "SUCCESS" else 1)


if __name__ == "__main__":
    main()
