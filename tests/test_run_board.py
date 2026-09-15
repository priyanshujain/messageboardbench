from pathlib import Path
import runpy
from unittest.mock import patch

import pytest

SCRIPT = Path(__file__).parents[1] / 'scripts/run_board.py'
REVISION = 'a' * 40


def test_interactive_defaults_preserve_matched_pilot():
    module = runpy.run_path(str(SCRIPT))
    values = iter(['', REVISION, '', '', '', '', '', ''] + [''] * 12)
    args = module['interactive_arguments'](lambda _: next(values))
    config = dict(zip(args[::2], args[1::2]))
    assert config['--model'] == 'glm'
    assert config['--dataset-revision'] == REVISION
    assert config['--agents-per-cohort'] == '2'
    assert config['--cohorts'] == '2'
    assert config['--teams'] == '2'
    assert config['--sampling'] == 'balanced-repeat'
    assert config['--prompt-variant'] == 'D'
    assert '--execute' not in args


def test_different_population_prompts_sampling_and_contributor():
    module = runpy.run_path(str(SCRIPT))
    values = iter(['muse', REVISION, '', '', '', '', '', '', '3', '2', '3'] + [''] * 9)
    args = module['interactive_arguments'](lambda _: next(values))
    config = dict(zip(args[::2], args[1::2]))
    assert config['--model'] == 'muse'
    assert config['--sampling'] == 'balanced-repeat'
    assert config['--teams'] == '3'


def test_invalid_number_reprompts():
    module = runpy.run_path(str(SCRIPT))
    values = iter(['0', '-1', 'abc', '2'])
    assert module['ask']('Agents', 3, module['positive'],
                         input_fn=lambda _: next(values)) == '2'


def test_forwarding_keeps_paths_and_model_literal_and_preview_default():
    module = runpy.run_path(str(SCRIPT))
    with patch('subprocess.run') as run:
        run.return_value.returncode = 0
        assert module['main'](['--model', 'openrouter/vendor/model',
                              '--out', 'logs/path with spaces']) == 0
    argv = run.call_args.args[0]
    assert argv[-1] == 'logs/path with spaces'
    assert '--execute' not in argv
    assert run.call_args.kwargs.get('shell', False) is False


def test_execute_is_explicit_and_child_failure_propagates():
    module = runpy.run_path(str(SCRIPT))
    with patch('subprocess.run') as run:
        run.return_value.returncode = 7
        assert module['main'](['--execute']) == 7
    assert run.call_args.args[0][-1] == '--execute'


def test_cancelled_interactive_never_launches():
    with patch('builtins.input', side_effect=EOFError), patch('subprocess.run') as run:
        module = runpy.run_path(str(SCRIPT))
        assert module['main'](['--interactive', '--execute']) == 130
        run.assert_not_called()


def test_preview_cannot_be_overridden_to_spend():
    module = runpy.run_path(str(SCRIPT))
    with patch('subprocess.run') as run, pytest.raises(SystemExit):
        module['main'](['--preview', '--execute'])
    run.assert_not_called()


def test_child_interrupt_does_not_claim_no_run_started(capsys):
    module = runpy.run_path(str(SCRIPT))
    with patch('subprocess.run', side_effect=KeyboardInterrupt):
        assert module['main'](['--execute']) == 130
    message = capsys.readouterr().err
    assert 'Runner interrupted' in message
    assert 'no experiment started' not in message
