from copy import deepcopy

import pytest

from messageboardbench.communication_plan import (
    build_communication_plan,
    verify_communication_plan,
)


def binding():
    return {
        "teams": 3,
        "model": "openrouter/example/model",
        "schedule": [{"team": 1, "cohort": 1, "condition": "sham"}],
    }


def test_plan_binds_configuration_and_analysis() -> None:
    frozen = build_communication_plan(binding())
    verify_communication_plan(frozen, binding())
    assert frozen["analysis"]["unit_of_assignment_and_inference"].startswith("independent")
    assert frozen["analysis"]["estimand"].startswith("intention-to-treat")
    assert frozen["analysis"]["primary_label_workflow"]["primary_labels_frozen_before_unblinding"]
    assert frozen["failure_handling"]["sample_retries"] == 0


def test_plan_rejects_too_few_teams_tampering_and_config_drift() -> None:
    with pytest.raises(ValueError, match="at least two"):
        build_communication_plan({"teams": 1})
    frozen = build_communication_plan(binding())
    tampered = deepcopy(frozen)
    tampered["analysis"]["point_estimator"] = "changed after freezing"
    with pytest.raises(ValueError, match="self-hash"):
        verify_communication_plan(tampered, binding())
    changed = {**binding(), "model": "openrouter/other/model"}
    with pytest.raises(ValueError, match="configuration"):
        verify_communication_plan(frozen, changed)
