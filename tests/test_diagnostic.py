from pathlib import Path
import runpy

import pytest

script = runpy.run_path(str(Path(__file__).parents[1] / "scripts" / "diagnostic.py"))


def test_defaults_are_preview_and_two_samples():
    args = script["parser"]().parse_args(["--out", "logs/example"])
    config, seeds = script["configuration"](args)
    assert not args.execute
    assert len(config["ids"]) == 2
    assert config["concurrency"] == 2
    assert not seeds


def test_large_diagnostic_batch_rejected():
    args = script["parser"]().parse_args(["--out", "logs/example", "--ids", *map(str, range(40))])
    with pytest.raises(ValueError, match="1–8"):
        script["configuration"](args)


def test_seed_manifest_identifies_input(tmp_path):
    p = tmp_path / "reference.py"
    p.write_text("# actual donor content\n")
    args = script["parser"]().parse_args(["--out", "logs/example", "--seed-file", str(p)])
    config, seeds = script["configuration"](args)
    assert seeds[p.name] == p.read_text()
    assert config["seed_files"][p.name]["source"] == str(p.resolve())
    assert len(config["seed_files"][p.name]["sha256"]) == 64
