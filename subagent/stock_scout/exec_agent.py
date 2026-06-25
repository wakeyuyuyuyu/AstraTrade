from __future__ import annotations

import json
from subagent.stock_scout.stock_scout import run_scout


def main():
    results = run_scout()
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
