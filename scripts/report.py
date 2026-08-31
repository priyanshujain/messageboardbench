"""Rebuild the CSV and the hand-read file from an eval log, without re-running anything.

    uv run python scripts/report.py logs/pilot
"""

import sys
from pathlib import Path

from inspect_ai.log import list_eval_logs, read_eval_log

from messageboardbench.analysis import rows, summarise, write_csv

sys.path.insert(0, str(Path(__file__).parent))
from pilot import write_hand_read_file  # noqa: E402

if __name__ == "__main__":
    log_dir = sys.argv[1] if len(sys.argv) > 1 else "logs/pilot"
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("results")

    samples = []
    for info in list_eval_logs(log_dir):
        samples.extend(read_eval_log(info.name).samples or [])

    table = rows(samples)
    write_csv(table, out / "pilot.csv")
    n_files = write_hand_read_file(samples, out / "pilot-scratch-contents.md")

    s = summarise(table)
    for k, v in s.items():
        print(f"{k:18} {v}")
    print(f"{'files left':18} {n_files}")
