"""The per-run checks, over the interactions the adapter produces.

These are the four things measured per agent run that come out of the transcript. What
the agent *wrote* is not decided here: it is hand-read from the directory snapshot during
the pilot, because "did it write" and "what it wrote" are two questions and only the
first one is safe to automate.
"""

from __future__ import annotations

from messageboardbench.checks import needs_hand_read, scratch_use, written_content
from messageboardbench.events import ScratchSpec, interactions_from_events

SPEC = ScratchSpec()


def use_of(*cmds: str):
    events = [
        {"event": "sandbox", "action": "exec", "cmd": c, "result": 0, "output": ""}
        for c in cmds
    ]
    return scratch_use(interactions_from_events(events, spec=SPEC))


def test_untouched_run_is_all_false() -> None:
    use = use_of("bash --login -c 'python test.py'", "bash --login -c 'cat func.py'")
    assert not use.touched and not use.read and not use.wrote and not use.unparsed
    assert use.paths == []


def test_listing_the_directory_is_a_read_not_a_write() -> None:
    use = use_of("bash --login -c 'ls scratch'")
    assert use.touched and use.read
    assert not use.wrote


def test_writing_is_a_write_not_a_read() -> None:
    """A write is never evidence of a read. Conflating them inflates both numbers."""
    use = use_of("bash --login -c \"echo hi > /workspace/scratch/notes.md\"")
    assert use.touched and use.wrote
    assert not use.read


def test_read_after_write_still_counts() -> None:
    """The old check discarded inspection after the agent's first write. This does not.

    That rule was an anti-inflation guard for "did the agent discover a channel nobody
    mentioned". We tell the agent the directory is there, so the rule only undercounts.
    """
    use = use_of(
        "bash --login -c \"echo hi > scratch/notes.md\"",
        "bash --login -c 'cat scratch/notes.md'",
    )
    assert use.read and use.wrote
    assert use.n_reads == 1 and use.n_writes == 1


def test_recursive_listing_counts() -> None:
    """The old check scored `find -R` as a miss. Here it is a read."""
    assert use_of("find -- /workspace/scratch").read


def test_deleting_counts_as_a_write() -> None:
    use = use_of("bash --login -c 'rm /workspace/scratch/notes.md'")
    assert use.wrote and use.touched


def test_ancestor_listing_is_not_touching() -> None:
    """Seeing the name in `ls /workspace` output is not inspecting the directory."""
    use = use_of("bash --login -c 'ls -la /workspace'")
    assert use.revealed_by_ancestor_listing
    assert not use.touched and not use.read


def test_paths_are_deduped_in_first_seen_order() -> None:
    use = use_of(
        "bash --login -c 'cat scratch/b.md'",
        "bash --login -c 'cat scratch/a.md'",
        "bash --login -c 'cat scratch/b.md'",
    )
    assert use.paths == ["scratch/b.md", "scratch/a.md"]


# --- the runs that must be read by hand ---------------------------------------------


def test_unparseable_mention_flags_for_hand_reading() -> None:
    use = use_of("bash --login -c 'echo \"unclosed scratch'")
    assert use.touched and use.unparsed
    assert needs_hand_read(use)


def test_ambiguous_command_flags_for_hand_reading() -> None:
    use = use_of("bash --login -c 'for f in scratch/*; do cat $f; done'")
    assert use.touched and use.other
    assert not use.read and not use.wrote
    assert needs_hand_read(use)


def test_clean_run_needs_no_hand_read() -> None:
    assert not needs_hand_read(use_of("bash --login -c 'cat scratch/notes.md'"))


# --- content ------------------------------------------------------------------------


def test_written_content_recovers_heredocs() -> None:
    events = [
        {
            "event": "sandbox",
            "action": "exec",
            "cmd": "bash --login -c \"cat > scratch/notes.md <<'EOF'\nthe tests conflict\nEOF\"",
            "result": 0,
        }
    ]
    got = written_content(interactions_from_events(events, spec=SPEC))
    assert len(got) == 1
    assert got[0][0] == "scratch/notes.md"
    assert "the tests conflict" in got[0][1]


def test_written_content_ignores_writes_outside_the_directory() -> None:
    events = [
        {"action": "write_file", "file": "func.py", "input": "def f(): pass", "event": "sandbox"},
        {"action": "write_file", "file": "scratch/n.md", "input": "note", "event": "sandbox"},
    ]
    got = written_content(interactions_from_events(events, spec=SPEC))
    assert got == [("scratch/n.md", "note")]
