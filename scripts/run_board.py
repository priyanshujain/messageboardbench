"""Interactive configuration and argument forwarding for the board experiment.

No provider requests are made by this launcher. The runner previews by default;
--execute explicitly starts the configured experiment.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import re
import subprocess
import sys

from messageboardbench.prompt_calibration import DEFAULT_PARTITIONS

ROOT = Path(__file__).resolve().parents[1]
CONFIRMATORY_POOL_SIZE = len(DEFAULT_PARTITIONS.communication_holdout)


def fresh_output() -> str:
    return 'logs/board-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')


def ask(label, default, convert=str, *, choices=None, input_fn=input):
    while True:
        value = input_fn(f'{label} [{default}]: ').strip() or str(default)
        try:
            parsed = convert(value)
            if choices is not None and parsed not in choices:
                raise ValueError('choose ' + ', '.join(map(str, choices)))
            return str(parsed)
        except ValueError as exc:
            print(f'Invalid value: {exc}', file=sys.stderr)


def positive(value):
    number = int(value)
    if number < 1:
        raise ValueError('must be a positive integer')
    return number


def temperature(value):
    number = float(value)
    if not 0 <= number <= 2:
        raise ValueError('must be between 0 and 2')
    return number


def immutable_revision(value):
    revision = str(value).lower()
    if not re.fullmatch(r'[0-9a-f]{40}', revision):
        raise ValueError('must be a full 40-character hexadecimal commit')
    return revision


def interactive_arguments(input_fn=input):
    def prompt(label, default, convert=str, **kwargs):
        return ask(label, default, convert, input_fn=input_fn, **kwargs)

    print('Model: glm = GLM 5.3 Flash; muse = Muse Spark 1.3 Contributor.\n'
          'You may also enter a full OpenRouter model ID.\n'
          'Each independent team runs matched sham-board and shared-board conditions.\n'
          'Both conditions expose the same neutral board prompt and tools.\n'
          'Confirmatory execution requires reviewed holdout-audit, calibration-plan, '
          'and communication-plan JSON files.')
    model = prompt('Model', 'glm')
    revision = prompt('Dataset revision (40-character commit)', 'REQUIRED', immutable_revision)
    holdout_audit = prompt('Holdout audit JSON (blank leaves preview blocked)', '')
    calibration_plan = prompt('Frozen calibration plan JSON', '')
    calibration_run = prompt('Completed corrected calibration run directory', '')
    calibration_review = prompt('Ready calibration behavior review JSON', '')
    validation_evidence = prompt('Ready one-shot prompt-D validation JSON', '')
    communication_plan = prompt('Frozen communication plan JSON', '')
    agents = prompt('Concurrent agents per cohort', 2, positive)
    cohorts = prompt('Sequential cohorts per team', 2, positive)
    teams = prompt('Independent matched teams', 2, positive)
    slots = int(agents) * int(cohorts)
    sampling = prompt(
        'Task sampling: fixed / balanced-repeat / with-replacement / without-replacement',
        'fixed' if slots == CONFIRMATORY_POOL_SIZE else 'balanced-repeat',
        choices=('fixed', 'balanced-repeat', 'with-replacement', 'without-replacement'),
    )
    if sampling == 'fixed' and slots != CONFIRMATORY_POOL_SIZE:
        raise ValueError(f'The interactive confirmatory pool has {CONFIRMATORY_POOL_SIZE} task pairs. '
                         f'Use {CONFIRMATORY_POOL_SIZE} slots, '
                         'choose sampling, or supply --ids/--splits noninteractively.')
    if sampling == 'without-replacement' and slots > CONFIRMATORY_POOL_SIZE:
        raise ValueError(f'The interactive confirmatory pool has {CONFIRMATORY_POOL_SIZE} task pairs; '
                         'reduce the slots or '
                         'use balanced-repeat or with-replacement. Custom pools use --ids/--splits.')
    seed = prompt('Sampling and schedule seed', 908, int)
    messages = prompt('Messages per episode', 90, positive)
    tokens = prompt('Total tokens per episode (includes cached input)', 1000000, positive)
    seconds = prompt('Seconds per episode', 1800, positive)
    temp = prompt('Temperature', 1, temperature)
    reasoning = prompt('Reasoning effort', 'high',
                       choices=('none', 'minimal', 'low', 'medium', 'high', 'xhigh'))
    prompt_variant = prompt('Frozen prompt variant: A / B / C / D', 'D',
                            choices=('A', 'B', 'C', 'D'))
    out = prompt('Fresh output directory', fresh_output())
    print(f'Configured {2 * slots * int(teams)} episodes across both conditions.', flush=True)
    result = ['--model', model, '--dataset-revision', revision,
            '--agents-per-cohort', agents, '--cohorts', cohorts,
            '--teams', teams, '--sampling', sampling, '--seed', seed,
            '--messages', messages, '--token-limit', tokens, '--time-limit', seconds,
            '--temperature', temp, '--reasoning-effort', reasoning,
            '--prompt-variant', prompt_variant, '--out', out]
    if holdout_audit:
        result[4:4] = ['--holdout-audit', holdout_audit]
    if calibration_plan:
        result[4:4] = ['--calibration-plan', calibration_plan]
    if calibration_run:
        result[4:4] = ['--calibration-run', calibration_run]
    if calibration_review:
        result[4:4] = ['--calibration-review', calibration_review]
    if validation_evidence:
        result[4:4] = ['--validation-evidence', validation_evidence]
    if communication_plan:
        result[4:4] = ['--communication-plan', communication_plan]
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, add_help=False)
    parser.add_argument('--interactive', action='store_true')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--execute', action='store_true')
    mode.add_argument('--preview', action='store_true')
    options, forwarded = parser.parse_known_args(argv)
    launched = False
    try:
        if options.interactive:
            if forwarded:
                parser.error('Use --interactive alone (optionally --execute); '
                             'pass runner flags without --interactive.')
            forwarded = interactive_arguments()
        elif not any(a == '--out' or a.startswith('--out=') for a in forwarded):
            forwarded += ['--out', fresh_output()]
        if options.execute:
            forwarded.append('--execute')
        launched = True
        return subprocess.run([sys.executable, str(ROOT / 'scripts/board_pilot.py'),
                               *forwarded], cwd=ROOT).returncode
    except (EOFError, KeyboardInterrupt):
        message = ('Runner interrupted; check the output directory for saved progress.'
                   if launched else 'Configuration cancelled; no experiment started.')
        print('\n' + message, file=sys.stderr)
        return 130
    except ValueError as exc:
        parser.error(str(exc))


if __name__ == '__main__':
    raise SystemExit(main())
