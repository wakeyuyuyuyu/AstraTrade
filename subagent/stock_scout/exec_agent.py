from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from subagent.stock_scout.stock_scout import run_scout

if __name__ == "__main__":
    results = run_scout()
    print("done")
