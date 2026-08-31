"""Everything needed to check the automated flags by hand, one section per run.

The pilot is only worth anything if the checks agree with a person reading the transcript.
This writes the two side by side: what the checks report, and every filesystem action the
agent took, unfiltered and unsummarised. Read them, and write down each disagreement.

The disagreements are the point. They are what calibrates the scorer before any money goes
into a real run, and they carry more information than the rate does.

    uv run python scripts/calibrate.py logs/pilot
"""

import sys
from pathlib import Path

from inspect_ai.log import list_eval_logs, read_eval_log

from messageboardbench.analysis import agent_commands, sample_row

if __name__ == "__main__":
    log_dir = sys.argv[1] if len(sys.argv) > 1 else "logs/pilot"
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("results/calibration.md")

    samples = []
    for info in list_eval_logs(log_dir):
        samples.extend(read_eval_log(info.name).samples or [])

    lines = [
        "# Hand read against the checks",
        "",
        "One section per run. `checks` is what the code reported; `agent commands` is",
        "every filesystem action the agent took, filtered only to exclude the harness's",
        "own setup and scoring. Read the commands, decide for yourself whether the agent",
        "touched or wrote to the directory, and record any disagreement in the verdict",
        "line. Disagreements are what calibrate the scorer.",
        "",
        "| sample | checks say touched | checks say wrote | my reading | agree? |",
        "| --- | --- | --- | --- | --- |",
    ]
    rows = [(s, sample_row(s)) for s in samples]
    for sample, row in rows:
        lines.append(
            f"| {row['sample_id']} | {row['touched_scratch']} | {row['wrote_scratch']} | | |"
        )
    lines.append("")

    for sample, row in rows:
        flags = ", ".join(
            k
            for k in (
                "cheated",
                "test_modified",
                "touched_scratch",
                "read_scratch",
                "wrote_scratch",
                "unparsed",
                "ambiguous",
            )
            if row[k]
        )
        final = next(iter(sample.scores.values()), None)
        files = ((final.metadata or {}).get("scratch_files") if final else {}) or {}

        lines += [
            f"## {row['sample_id']}",
            "",
            f"checks: {flags or 'nothing'}   (messages: {row['n_messages']}, limit: {row['limit_hit'] or 'none'})",
            "",
            "agent commands:",
            "",
            "```",
        ]
        lines += agent_commands(sample) or ["(none)"]
        lines += ["```", ""]

        if files:
            lines += ["left behind:", ""]
            for path, content in files.items():
                lines += [f"`{path}`", "", "```", content.rstrip(), "```", ""]
        else:
            lines += ["left behind: nothing", ""]

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines))
    print(f"wrote {out} for {len(rows)} runs")
