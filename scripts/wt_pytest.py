"""Run pytest against THIS checkout's src/ (a worktree beside an editable install of another one).

    python3 scripts/wt_pytest.py -q tests/
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

if __name__ == "__main__":
    sys.exit(pytest.main(sys.argv[1:] or ["-q", "tests/"]))
