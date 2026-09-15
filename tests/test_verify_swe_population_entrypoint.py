import runpy
from pathlib import Path
import subprocess
import sys


def test_verify_swe_population_script_imports_when_invoked_by_path_from_repo_root():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "scripts/analysis/verify_swe_population.py", "--help"],
        cwd=root, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "--run" in result.stdout and "--export" in result.stdout


def test_board_operations_are_linked_to_board_episodes_without_condition_field():
    root = Path(__file__).resolve().parents[1]
    namespace = runpy.run_path(root / "scripts/analysis/verify_swe_population.py")
    board_operations_are_board_only = namespace["board_operations_are_board_only"]
    rows = [
        {"episode_id": "control-1", "condition": "control"},
        {"episode_id": "board-1", "condition": "board"},
    ]
    assert board_operations_are_board_only(rows, [{"episode_id": "board-1"}])
    assert not board_operations_are_board_only(rows, [{"episode_id": "control-1"}])
    assert not board_operations_are_board_only(rows, [{"episode_id": "unknown"}])
