#!/usr/bin/env python3
"""Bootstrap local workbench directories and config."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lib.local_config import ensure_local_runtime


def main():
    data_dir = ROOT / "data"
    ensure_local_runtime(data_dir)
    print("bootstrapped", data_dir)
    print("config", data_dir / "config.json")


if __name__ == "__main__":
    main()
