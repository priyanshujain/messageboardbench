from __future__ import annotations

import json
from pathlib import Path
import runpy

import pytest
from inspect_ai.dataset import Sample

from messageboardbench.prompt_calibration import (
    DEFAULT_PARTITIONS,
    NO_TEST_EDITING,
    PROMPT_VARIANTS,
    TaskPartitions,
    apply_variant_to_sample,
    build_manifest,
    render_tools_instruction,
    write_manifest,
)


def test_variants_are_exact_predefined_impossiblebench_family() -> None:
    assert [variant.variant_id for variant in PROMPT_VARIANTS] == [
        "A", "B", "C", "D"
    ]
    assert all(variant.published_prompt.endswith(NO_TEST_EDITING) for variant in PROMPT_VARIANTS)
    assert "pass all tests" in render_tools_instruction("A")
    assert "STOP" in render_tools_instruction("D")
    assert "carve out" in render_tools_instruction("D")


def test_manifest_freezes_disjoint_partitions_and_balanced_assignments() -> None:
    manifest = build_manifest(dataset_revision="a" * 40, replicates=2)
    assert manifest["purpose"] == "prompt-calibration-development-only"
    assert manifest["separate_from_confirmatory_communication"] is True
    assert len(manifest["development_assignments"]) == (
        len(DEFAULT_PARTITIONS.development) * len(PROMPT_VARIANTS) * 2 * 2
    )
    counts = {}
    for assignment in manifest["development_assignments"]:
        key = (assignment["task_id"], assignment["split"], assignment["prompt_variant"])
        counts[key] = counts.get(key, 0) + 1
    assert set(counts.values()) == {2}
    assert manifest["validation_policy"]["development_estimates_prompt_sensitivity"] is True
    assert manifest["validation_policy"]["communication_holdout_must_not_run_during_calibration"] is True
    assert manifest["confirmatory_prompt_policy"]["variant"] == "D"
    assert manifest["confirmatory_prompt_policy"]["chosen_before_calibration_outcomes"] is True
    assert manifest["environment"]["completion_policy"] == {
        "mode": "plain-assistant-final-or-submit",
        "adds_model_visible_tools": False,
        "adds_model_visible_wording": False,
        "plain_text_final_ends_episode": True,
        "plain_text_final_preserved_in_metadata": True,
        "plain_text_final_requires_review": True,
        "artifact_scored_normally": True,
        "installed_identically_across_conditions": True,
        "scaffold_deviation": (
            "Treats an assistant response without tool calls as a terminal response instead "
            "of adding Inspect basic_agent's continuation message"
        ),
    }
    assert {row["split"] for row in manifest["development_assignments"]} == {
        "original", "conflicting"
    }
    assert {row["prompt_variant"] for row in manifest["validation_assignments"]} == {"D"}


def test_variant_has_an_unambiguous_future_injection_path() -> None:
    manifest = build_manifest(dataset_revision="a" * 40)
    prompt_d = next(
        row for row in manifest["prompt_variants"]
        if row["variant_id"] == "D"
    )
    assert prompt_d["injection"] == "record_to_sample_instruction_prompt"
    assert prompt_d["rendered_tools_instruction"] == render_tools_instruction("D")
    assert prompt_d["rendered_tools_instruction"].count(NO_TEST_EDITING) == 1
    assert manifest["benchmark"]["task_prompt_and_tests_unchanged_across_variants"] is True


def test_apply_variant_changes_only_instruction_and_records_variant() -> None:
    original_instruction = render_tools_instruction("A")
    sample = Sample(
        id="lcbhard_0",
        input=original_instruction,
        metadata={
            "instruction_prompt": original_instruction,
            "prompt": "def f():",
            "test": "def check(candidate): pass",
            "entry_point": "f",
            "impossible_type": "conflicting",
        },
    )
    changed = apply_variant_to_sample(sample, "D")
    assert changed.input == render_tools_instruction("D")
    assert changed.metadata["instruction_prompt"] == render_tools_instruction("D")
    assert changed.metadata["prompt_variant"] == "D"
    for key in ("prompt", "test", "entry_point", "impossible_type"):
        assert changed.metadata[key] == sample.metadata[key]
    assert sample.metadata.get("prompt_variant") is None


def test_apply_variant_refuses_inline_task_input() -> None:
    sample = Sample(
        id="x", input="instruction plus inline task",
        metadata={"instruction_prompt": "instruction"},
    )
    with pytest.raises(ValueError, match="tools-scaffold"):
        apply_variant_to_sample(sample, "D")


def test_manifest_is_reproducible_for_a_seed() -> None:
    first = build_manifest(dataset_revision="a" * 40, seed=123)
    second = build_manifest(dataset_revision="a" * 40, seed=123)
    assert first == second
    assert first["development_assignments"] != build_manifest(
        dataset_revision="a" * 40, seed=124
    )["development_assignments"]


def test_partition_overlap_and_unpinned_revision_fail_closed() -> None:
    overlap = TaskPartitions(("a",), ("a",), ("b",))
    with pytest.raises(ValueError, match="overlap"):
        build_manifest(partitions=overlap, dataset_revision="a" * 40)
    with pytest.raises(ValueError, match="40-character"):
        build_manifest(dataset_revision="UNPINNED")
    with pytest.raises(ValueError, match="40-character"):
        build_manifest(dataset_revision="rev")
    with pytest.raises(ValueError, match="requires A-D"):
        build_manifest(dataset_revision="a" * 40, variant_ids=("B", "C", "D"))


def test_manifest_write_is_exclusive(tmp_path: Path) -> None:
    path = tmp_path / "plan.json"
    manifest = build_manifest(dataset_revision="a" * 40)
    write_manifest(path, manifest)
    assert json.loads(path.read_text()) == manifest
    with pytest.raises(FileExistsError):
        write_manifest(path, manifest)


def test_cli_is_preview_only_without_out(capsys: pytest.CaptureFixture[str]) -> None:
    script = runpy.run_path(str(Path(__file__).parents[1] / "scripts" / "prompt_calibration.py"))
    args = script["parser"]().parse_args(["--dataset-revision", "a" * 40])
    manifest = script["configuration"](args)
    assert manifest["environment"]["communication"] == "none"
    assert args.out is None
