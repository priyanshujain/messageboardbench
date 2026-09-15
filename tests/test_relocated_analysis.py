"""Portable analysis must preserve frozen evidence and reject output reuse."""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

BENCH = Path(__file__).resolve().parents[1]


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, BENCH / f'scripts/analysis/{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def digest_tree(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file()}


def test_synthesis_reproduces_frozen_metrics_without_changing_sources(tmp_path, capsys):
    v1 = BENCH / 'results/board-pilot-sept8'
    v2 = BENCH / 'results/board-interface-v2-sept8'
    if not v1.is_dir() or not v2.is_dir():
        pytest.skip('Local frozen pilot evidence not installed')
    before = [digest_tree(v1), digest_tree(v2)]
    out = tmp_path / 'derived'
    script = load_script('board_synthesis')
    args = ['--results-v1', str(v1), '--results-v2', str(v2), '--out', str(out)]
    script.main(args)
    for name in ['token-summary.json', 'reviewed-episodes.json']:
        assert json.loads((out / name).read_text()) == json.loads((v2 / name).read_text())
    assert before == [digest_tree(v1), digest_tree(v2)]
    with pytest.raises(FileExistsError):
        script.main(args)
    assert before == [digest_tree(v1), digest_tree(v2)]


def test_synthesis_rejects_output_inside_source(tmp_path):
    source = tmp_path / 'frozen'
    source.mkdir()
    with pytest.raises(SystemExit):
        load_script('board_synthesis').main([
            '--results-v1', str(source), '--results-v2', str(source),
            '--out', str(source / 'derived')])
    assert list(source.iterdir()) == []


def test_token_audit_rejects_partial_input_before_creating_output(tmp_path):
    logs = tmp_path / 'logs'
    logs.mkdir()
    out = tmp_path / 'derived'
    with pytest.raises(SystemExit):
        load_script('token_audit').main(['--logs', str(logs), '--out', str(out)])
    assert not out.exists()


def test_token_audit_rejects_output_inside_logs(tmp_path):
    logs = tmp_path / 'logs'
    logs.mkdir()
    with pytest.raises(SystemExit):
        load_script('token_audit').main(['--logs', str(logs), '--out', str(logs / 'derived')])
    assert list(logs.iterdir()) == []
