"""Run and repeat the frozen ATR boundary structure-only qualification."""
from __future__ import annotations

import json

from research.atr_boundary_qualification import (
    canonical_payload_digest,
    run_qualification,
    write_outputs,
)


def main() -> int:
    first = run_qualification()
    first_digest = canonical_payload_digest(first)
    second = run_qualification()
    second_digest = canonical_payload_digest(second)
    reproducible = first_digest == second_digest
    first["reproducibility"] = {
        "required": True,
        "status": "PASS" if reproducible else "FAIL",
        "method": "same frozen input and protocol, second full structure-only run",
        "first_canonical_digest": first_digest,
        "second_canonical_digest": second_digest,
    }
    result = write_outputs(first)
    print(json.dumps({
        "status": first["status"] if reproducible else "QUALIFICATION_REPRODUCIBILITY_FAILURE",
        "next": first["next"],
        "qualified_candidates": first["qualification"]["qualified_candidates"] if reproducible else [],
        "reproducibility": first["reproducibility"],
        "parity": first["parity"],
        "output_dir": str(result["output_dir"]),
    }, ensure_ascii=False, sort_keys=True))
    return 0 if reproducible and first["parity"]["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
