"""Render a standalone read-only dashboard from a saved Daily Decision JSON."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from trading.daily_dashboard import load_dashboard_json, write_dashboard_html


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="将既有 Production Daily Decision JSON 渲染为只读 HTML dashboard"
    )
    parser.add_argument("input_json", type=Path, help="Production Daily Decision JSON 文件")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("reports/daily_dashboard"),
        help="HTML 输出目录（默认：reports/daily_dashboard）",
    )
    args = parser.parse_args(argv)
    paths = write_dashboard_html(
        load_dashboard_json(args.input_json),
        args.output_dir,
    )
    for path in paths:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
