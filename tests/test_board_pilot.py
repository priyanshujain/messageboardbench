"""Offline planning and orchestration checks; never call a model provider."""
import asyncio
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from messageboardbench.prompt_calibration import render_tools_instruction
from messageboardbench.prompt_calibration import build_manifest, write_manifest
from messageboardbench.calibration_run import read_frozen_manifest
from messageboardbench.completion import completion_manifest_record
from messageboardbench.confirmation import (
    verify_completed_calibration, verify_completed_prompt_d_validation,
)

spec = importlib.util.spec_from_file_location("board_pilot", Path(__file__).parents[1] / "scripts/board_pilot.py")
pilot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pilot)

REVISION = 'a' * 40
TASK_PROMPT = 'def f(): pass'
TEST_CODE = 'def check(candidate): pass'


def args(*extra):
    return pilot.parser().parse_args([
        "--out", "unused", "--dataset-revision", REVISION, *extra
    ])


def make_sample(task_id):
    instruction = render_tools_instruction('A')
    from inspect_ai.dataset import Sample
    return Sample(id=task_id, input=instruction, metadata={
        'instruction_prompt': instruction, 'prompt': TASK_PROMPT,
        'test': TEST_CODE, 'entry_point': 'f',
    })


def write_audit(path, pairs=None):
    pairs = pairs or list(zip(pilot.DEFAULT_IDS, pilot.DEFAULT_SPLITS))
    data = {
        'schema_version': 2, 'status': 'ready',
        'dataset': {'path': 'fjzzq2002/impossible_livecodebench', 'revision': REVISION},
        'review': {'reviewer_type': 'human', 'reviewer': 'Test reviewer', 'reviewers': [],
                   'no_model_outcomes_inspected': True},
        'approved_pairs': [{
            'task_id': task_id, 'split': split, 'task_validated': True,
            'evaluator_validated': True,
            'task_prompt_sha256': hashlib.sha256(TASK_PROMPT.encode()).hexdigest(),
            'test_sha256': hashlib.sha256(TEST_CODE.encode()).hexdigest(),
        } for task_id, split in pairs],
    }
    path.write_text(json.dumps(data))
    return path


def write_calibration(path, **kwargs):
    write_manifest(path, build_manifest(dataset_revision=REVISION, **kwargs))
    return path


def write_completed_calibration(plan_path, run_path):
    plan, source = read_frozen_manifest(plan_path)
    run_path.mkdir()
    (run_path / 'evals').mkdir()
    (run_path / 'frozen-plan.json').write_bytes(plan_path.read_bytes())
    rows = [{
        'assignment': assignment, 'error': None,
        'sample_id': assignment['task_id'],
        'log': str(run_path / 'evals' / f'{index}.eval'),
        'completion': completion_manifest_record(),
        'calibration': {'communication': 'none'},
    } for index, assignment in enumerate(plan['development_assignments'], 1)]
    for row in rows:
        Path(row['log']).write_bytes(b'mock eval log')
    (run_path / 'results.json').write_text(json.dumps(rows))
    (run_path / 'status.json').write_text(json.dumps({
        'status': 'completed', 'phase': 'development',
        'completed_assignments': len(rows), 'in_flight_assignment': None,
    }))
    (run_path / 'run-manifest.json').write_text(json.dumps({
        'purpose': 'prompt-calibration-development-execution', 'phase': 'development',
        'execute': True, 'communication': 'none', 'completion': completion_manifest_record(),
        'manifest': source,
    }))
    evidence = verify_completed_calibration(plan_path, run_path)
    review_path = run_path.parent / 'calibration-review.json'
    review_path.write_text(json.dumps({
        'schema_version': 1, 'status': 'ready',
        'purpose': 'prompt-calibration-behavior-review',
        'calibration_evidence_sha256': evidence['evidence_sha256'],
        'no_communication_holdout_outcomes_inspected': True,
        'reviewer': 'Test review group',
        'assignment_labels': [
            {'assignment_index': i, 'label': 'no_observed_gaming'}
            for i in range(1, len(rows) + 1)
        ],
        'prompt_d_assessment': {
            'decision': 'proceed', 'variation_adequate': True, 'rationale': 'Test fixture',
        },
    }))
    validation_run = run_path.parent / 'prompt-d-validation-run'
    validation_run.mkdir()
    (validation_run / 'evals').mkdir()
    (validation_run / 'frozen-plan.json').write_bytes(plan_path.read_bytes())
    validation_rows = [{
        'assignment': assignment, 'error': None,
        'sample_id': assignment['task_id'],
        'log': str(validation_run / 'evals' / f'{index}.eval'),
        'completion': completion_manifest_record(),
        'calibration': {
            'phase': 'validation', 'communication': 'none', 'assignment': assignment,
            'manifest': source, 'policy_prompt': {'variant': 'D'},
        },
    } for index, assignment in enumerate(plan['validation_assignments'], 1)]
    for row in validation_rows:
        Path(row['log']).write_bytes(b'mock validation eval log')
    (validation_run / 'results.json').write_text(json.dumps(validation_rows))
    (validation_run / 'status.json').write_text(json.dumps({
        'status': 'completed', 'phase': 'validation',
        'completed_assignments': len(validation_rows), 'in_flight_assignment': None,
    }))
    validation_manifest = {
        'purpose': 'prompt-calibration-validation-execution', 'phase': 'validation',
        'execute': True, 'communication': 'none', 'completion': completion_manifest_record(),
        'assignments': len(validation_rows), 'manifest': source,
    }
    validation_audit = run_path.parent / 'validation-audit.json'
    validation_audit.write_text(json.dumps({
        'schema_version': 2, 'status': 'ready', 'partition': 'validation',
        'dataset': {'path': plan['benchmark']['dataset'],
                    'revision': plan['benchmark']['dataset_revision']},
        'review': {'reviewer_type': 'human', 'reviewer': 'Test reviewer',
                   'no_model_outcomes_inspected': True},
        'approved_pairs': [{
            'task_id': task_id, 'split': split, 'task_validated': True,
            'evaluator_validated': True, 'task_prompt_sha256': '1' * 64,
            'test_sha256': '2' * 64,
        } for task_id, split in sorted({
            (row['task_id'], row['split']) for row in plan['validation_assignments']
        })],
    }))
    validation_manifest['validation_audit'] = {
        'path': str(validation_audit),
        'sha256': hashlib.sha256(validation_audit.read_bytes()).hexdigest(),
    }
    validation_manifest.update({key: plan['environment'][key] for key in (
        'model', 'message_limit', 'token_limit', 'time_limit_seconds', 'temperature',
        'reasoning_effort', 'max_attempts', 'strict_tools', 'sample_retries', 'request_retries',
    )})
    (validation_run / 'run-manifest.json').write_text(json.dumps(validation_manifest))
    validation_execution = verify_completed_prompt_d_validation(plan_path, validation_run)
    validation_path = run_path.parent / 'prompt-d-validation.json'
    validation_path.write_text(json.dumps({
        'schema_version': 1, 'status': 'ready', 'purpose': 'prompt-d-validation',
        'calibration_evidence_sha256': evidence['evidence_sha256'],
        'dataset_revision': REVISION, 'model': plan['environment']['model'],
        'prompt_variant': 'D',
        'prompt_sha256': hashlib.sha256(render_tools_instruction('D').encode()).hexdigest(),
        'communication': 'none', 'completion_policy': completion_manifest_record(),
        'communication_holdout_executed': False, 'artifact_review_complete': True,
        'validation_run_directory': str(validation_run),
        'validation_execution_sha256': validation_execution['evidence_sha256'],
        'decision': 'proceed', 'variation_adequate': True,
        'completed_assignments': len(validation_rows), 'reviewer': 'Test review group',
        'rationale': 'Test fixture validation has variation',
        'assignment_labels': [{
            'assignment_index': row['assignment_index'],
            'label': ('successful_gaming' if row['assignment_index'] == min(
                          item['assignment_index'] for item in plan['validation_assignments']
                          if item['split'] == 'conflicting')
                      else 'no_observed_gaming'),
            'artifact_labels': (['contradiction_targeted_gaming']
                                if row['assignment_index'] == min(
                                    item['assignment_index']
                                    for item in plan['validation_assignments']
                                    if item['split'] == 'conflicting')
                                else ['specification_faithful']),
            'notes': 'Artifact inspected and classified independently of score.',
        } for row in plan['validation_assignments']],
    }))
    return run_path, review_path, validation_path


def test_default_plan_uses_balanced_holdout_sampling():
    options = args()
    assert options.prompt_variant == 'D'
    assert options.sampling == 'balanced-repeat'
    teams, schedule = pilot.plan(options)
    assert len(teams) == 1
    assert len(teams[0]["ids"]) == 4
    assert set(zip(teams[0]["ids"], teams[0]["splits"])) <= set(
        zip(pilot.DEFAULT_IDS, pilot.DEFAULT_SPLITS)
    )
    assert [(s["cohort"], s["condition"]) for s in schedule] == [
        (1, "shared"), (1, "sham"), (2, "sham"), (2, "shared")]


def test_confirmatory_preview_fails_closed_before_dataset_load(monkeypatch, capsys):
    monkeypatch.setattr(pilot, 'load_pinned_datasets',
                        lambda *values: pytest.fail('blocked preview must not load tasks'))
    monkeypatch.setattr('sys.argv', ['board_pilot', '--out', 'unused',
                                    '--dataset-revision', REVISION])
    pilot.main()
    preview = json.loads(capsys.readouterr().out)
    assert preview['confirmatory_ready'] is False
    assert preview['dataset']['revision'] == REVISION
    assert 'holdout-audit' in preview['blockers'][0]


def test_confirmatory_rejects_development_ids_and_unpinned_revision(monkeypatch):
    with pytest.raises(SystemExit):
        pilot.parser().parse_args(['--out', 'unused', '--dataset-revision', 'main'])
    monkeypatch.setattr('sys.argv', ['board_pilot', '--out', 'unused',
        '--dataset-revision', REVISION, '--ids', 'lcbhard_0', '--splits', 'conflicting',
        '--agents-per-cohort', '1', '--cohorts', '1'])
    with pytest.raises(SystemExit):
        pilot.main()


def test_confirmatory_rejects_original_split_even_for_reserved_id(monkeypatch):
    monkeypatch.setattr('sys.argv', ['board_pilot', '--out', 'unused',
        '--dataset-revision', REVISION, '--ids', pilot.DEFAULT_IDS[0],
        '--splits', 'original', '--agents-per-cohort', '1', '--cohorts', '1'])
    with pytest.raises(SystemExit):
        pilot.main()


def test_holdout_execution_requires_frozen_communication_plan(tmp_path, monkeypatch):
    audit = write_audit(tmp_path / 'holdout-audit.json')
    monkeypatch.setattr('sys.argv', ['board_pilot', '--out', 'unused',
        '--dataset-revision', REVISION, '--holdout-audit', str(audit), '--execute'])
    with pytest.raises(SystemExit):
        pilot.main()


@pytest.mark.parametrize('variant', ['A', 'B', 'C', 'upstream-legacy'])
def test_nonconfirmatory_prompts_cannot_consume_communication_holdout(variant, monkeypatch):
    monkeypatch.setattr('sys.argv', ['board_pilot', '--out', 'unused',
        '--dataset-revision', REVISION, '--prompt-variant', variant])
    with pytest.raises(SystemExit, match='2'):
        pilot.main()


def test_nonconfirmatory_prompts_cannot_consume_validation_reserve(monkeypatch):
    monkeypatch.setattr('sys.argv', ['board_pilot', '--out', 'unused',
        '--dataset-revision', REVISION, '--prompt-variant', 'A',
        '--ids', 'lcbhard_3', '--splits', 'conflicting',
        '--agents-per-cohort', '1', '--cohorts', '1'])
    with pytest.raises(SystemExit):
        pilot.main()


def test_dataset_loader_passes_exact_immutable_revision(monkeypatch):
    import inspect_ai.dataset
    calls = []

    def fake_hf_dataset(**kwargs):
        calls.append(kwargs)
        return [make_sample('lcbhard_7')]

    monkeypatch.setattr(inspect_ai.dataset, 'hf_dataset', fake_hf_dataset)
    loaded = pilot.load_pinned_datasets({'conflicting'}, REVISION)
    assert set(loaded['conflicting']) == {'lcbhard_7'}
    assert calls[0]['path'] == 'fjzzq2002/impossible_livecodebench'
    assert calls[0]['split'] == 'conflicting'
    assert calls[0]['revision'] == REVISION


@pytest.mark.parametrize("sampling", ["with-replacement", "without-replacement"])
def test_sampling_reproducible_and_pool_pairs_preserved(sampling):
    options = args("--agents-per-cohort", "2", "--cohorts", "2", "--teams", "3", "--sampling", sampling)
    teams, schedule = pilot.plan(options)
    assert (teams, schedule) == pilot.plan(options)
    assert len(teams) == 3 and len(schedule) == 12
    pool = set(zip(pilot.DEFAULT_IDS, pilot.DEFAULT_SPLITS))
    for team in teams:
        pairs = list(zip(team["ids"], team["splits"]))
        assert len(pairs) == 4 and set(pairs) <= pool
        if sampling == "without-replacement":
            assert len(set(pairs)) == 4
        phases = [s for s in schedule if s["team"] == team["team"]]
        assert {(s["cohort"], s["condition"]) for s in phases} == {
            (c, condition) for c in (1, 2) for condition in pilot.CONDITIONS}


def test_balanced_repeat_balances_each_cohort_and_interleaves_teams():
    options = args(
        "--agents-per-cohort", "22", "--cohorts", "3", "--teams", "4",
        "--sampling", "balanced-repeat",
    )
    teams, schedule = pilot.plan(options)
    assert (teams, schedule) == pilot.plan(options)
    pool = set(zip(pilot.DEFAULT_IDS, pilot.DEFAULT_SPLITS))
    for team in teams:
        pairs = list(zip(team["ids"], team["splits"]))
        assert len(pairs) == 66
        for cohort in range(3):
            cohort_pairs = pairs[cohort * 22:(cohort + 1) * 22]
            assert set(cohort_pairs) == pool
            assert all(cohort_pairs.count(pair) == 2 for pair in pool)

    assert [row["cohort"] for row in schedule] == [1] * 8 + [2] * 8 + [3] * 8
    for offset in range(0, len(schedule), 2):
        block = schedule[offset:offset + 2]
        assert len({row["team"] for row in block}) == 1
        assert len({row["cohort"] for row in block}) == 1
        assert {row["condition"] for row in block} == set(pilot.CONDITIONS)


def test_balanced_repeat_generic_nondivisible_cohort():
    options = args(
        "--agents-per-cohort", "7", "--cohorts", "2", "--teams", "2",
        "--sampling", "balanced-repeat",
    )
    teams, _ = pilot.plan(options)
    pool = list(zip(pilot.DEFAULT_IDS, pilot.DEFAULT_SPLITS))
    for team in teams:
        pairs = list(zip(team["ids"], team["splits"]))
        for cohort in range(2):
            counts = [pairs[cohort * 7:(cohort + 1) * 7].count(pair) for pair in pool]
            assert max(counts) - min(counts) <= 1


@pytest.mark.parametrize("flags", [
    ("--agents-per-cohort", "1", "--sampling", "fixed"),
    ("--agents-per-cohort", "12", "--sampling", "without-replacement"),
    ("--ids", "lcbhard_0"),
    ("--ids", "lcbhard_0", "lcbhard_0", "--splits", "original", "original"),
])
def test_bad_plans_rejected(flags):
    with pytest.raises(ValueError):
        pilot.plan(args(*flags))


@pytest.mark.parametrize("flag", ["--agents-per-cohort", "--cohorts", "--teams", "--messages", "--token-limit", "--time-limit"])
def test_zero_budgets_and_sizes_rejected(flag):
    with pytest.raises(SystemExit):
        args(flag, "0")


@pytest.mark.parametrize("value", ["nan", "inf", "-1", "2.1"])
def test_invalid_temperature_rejected(value):
    with pytest.raises(SystemExit):
        args("--temperature", value)


def test_multiteam_execution_matches_conditions_and_isolates_boards(tmp_path, monkeypatch):
    import inspect_ai
    from inspect_ai.dataset import Sample
    import messageboardbench.board_task as board_task
    import messageboardbench.task as task_module
    calls, bindings = [], []
    monkeypatch.setattr(pilot, "budget", lambda: {"usage": 0, "limit": 5, "limit_remaining": 5})
    monkeypatch.setattr(pilot, 'load_pinned_datasets', lambda splits, revision: {
        split: {task_id: make_sample(task_id) for task_id in pilot.DEFAULT_IDS}
        for split in splits})
    monkeypatch.setattr(inspect_ai, "Task", lambda **kw: SimpleNamespace(**kw))
    monkeypatch.setattr(board_task, "episode_solver", lambda *values: bindings.append(values))
    monkeypatch.setattr(task_module, "scratch_scorer", lambda split: None)

    def evaluate(tasks, **kwargs):
        calls.append((tasks, kwargs))
        return [SimpleNamespace(location="mock.eval", status="success", eval=SimpleNamespace(metadata=t.metadata),
            samples=[SimpleNamespace(id=t.dataset[0].id, metadata=t.dataset[0].metadata, scores={},
                                     messages=[], model_usage={}, limit=None, error=None)]) for t in tasks]

    monkeypatch.setattr(inspect_ai, "eval", evaluate)
    out = tmp_path / "run"
    audit = write_audit(tmp_path / 'holdout-audit.json')
    calibration = write_calibration(
        tmp_path / 'calibration.json', message_limit=117, token_limit=12345,
        time_limit=321, temperature=0.5, reasoning_effort='low',
    )
    calibration_run, calibration_review, validation_evidence = write_completed_calibration(
        calibration, tmp_path / 'calibration-run'
    )
    communication = tmp_path / 'communication.json'
    common = ["board_pilot", "--out", str(out), "--teams", "2", "--agents-per-cohort", "2",
        "--cohorts", "2", "--sampling", "with-replacement", "--messages", "117", "--token-limit", "12345",
        "--time-limit", "321", "--temperature", "0.5", "--reasoning-effort", "low",
        "--dataset-revision", REVISION, "--holdout-audit", str(audit),
        "--calibration-plan", str(calibration),
        "--calibration-run", str(calibration_run),
        "--calibration-review", str(calibration_review),
        "--validation-evidence", str(validation_evidence)]
    monkeypatch.setattr("sys.argv", [*common, '--freeze-communication-plan', str(communication)])
    pilot.main()
    monkeypatch.setenv('DOCKER_HOST', pilot.REMOTE_DOCKER_HOST)
    monkeypatch.setattr("sys.argv", [*common, '--communication-plan', str(communication), "--execute"])
    pilot.main()
    assert len(calls) == 8
    for tasks, kwargs in calls:
        assert len(tasks) == 2
        assert kwargs["max_tasks"] == kwargs["max_samples"] == kwargs["max_sandboxes"] == 2
        assert kwargs["token_limit"] == 12345 and kwargs["time_limit"] == 321
        assert kwargs["temperature"] == 0.5 and kwargs["reasoning_effort"] == "low"
        assert all(t.message_limit == 117 for t in tasks)
    by_team_condition = {}
    episode_ids = []
    for tasks, _ in calls:
        for task in tasks:
            sample = task.dataset[0]
            meta = sample.metadata
            episode_ids.append(meta["episode_id"])
            by_team_condition.setdefault((meta["team"], meta["condition"]), []).append((sample.id, task.metadata["split"], meta["slot"]))
    assert len(episode_ids) == len(set(episode_ids)) == 16
    for team in (1, 2):
        assert by_team_condition[team, "sham"] == by_team_condition[team, "shared"]
    shared_boards = {v[4] for v in bindings if v[0] == "shared"}
    assert shared_boards == {out / "board-team-1.sqlite", out / "board-team-2.sqlite"}
    sham_boards = [v[4] for v in bindings if v[0] == "sham"]
    assert len(sham_boards) == len(set(sham_boards)) == 8
    assert all(path.name.startswith('sham-board-team-') for path in sham_boards)
    assert all(v[4] is not None for v in bindings)
    snapshot = json.loads((out / "board-final.json").read_text())
    assert len(set(snapshot["run_ids"])) == 10
    assert len(snapshot['stores']) == 10
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["planned_episodes"] == 16
    assert manifest['conditions'] == ['sham', 'shared']
    assert manifest['policy_prompt']['variant'] == 'D'
    assert manifest['policy_prompt']['rendered_instruction_prompt'] == render_tools_instruction('D')
    assert manifest['policy_prompt']['rendered_instruction_prompt_sha256']
    assert manifest['policy_prompt']['rendered_instruction_prompt_base64']
    assert manifest['dataset']['revision'] == REVISION
    assert manifest['dataset']['revision_kind'] == 'immutable_commit'
    assert manifest['dataset']['holdout_audit']['sha256']
    assert manifest['dataset']['approved_pair_hashes']
    assert manifest['confirmatory'] and manifest['confirmatory_ready']
    assert manifest['communication_plan']['status'] == 'verified-for-execution'
    assert manifest['calibration_plan']['sha256']
    assert manifest['calibration_execution']['evidence_sha256']
    assert manifest['calibration_review']['status'] == 'ready'
    assert manifest['prompt_d_validation']['status'] == 'ready'
    assert manifest['communication_plan_consumption']['status'] == 'consumed'
    assert manifest['completion']['mode'] == 'plain-assistant-final-or-submit'
    assert manifest['completion']['adds_model_visible_tools'] is False
    assert manifest['completion']['installed_identically_across_conditions']
    assert manifest['identical_board_prompt_and_tools_both_conditions']
    assert manifest['sham_posts_isolated_per_episode']
    assert json.loads((out / "status.json").read_text())["status"] == "completed"

    from messageboardbench.board import board_tools
    shared = [v for v in bindings if v[0] == 'shared']
    shared_post, _ = board_tools(shared[0][4], shared[0][3], shared[0][1], shared[0][2])
    _, shared_read = board_tools(shared[1][4], shared[1][3], shared[1][1], shared[1][2])
    asyncio.run(shared_post('shared text'))
    assert json.loads(asyncio.run(shared_read()))['posts'][0]['text'] == 'shared text'

    sham = [v for v in bindings if v[0] == 'sham']
    sham_post, sham_self_read = board_tools(sham[0][4], sham[0][3], sham[0][1], sham[0][2])
    _, other_sham_read = board_tools(sham[1][4], sham[1][3], sham[1][1], sham[1][2])
    asyncio.run(sham_post('isolated text'))
    assert json.loads(asyncio.run(sham_self_read()))['posts'][0]['text'] == 'isolated text'
    assert json.loads(asyncio.run(other_sham_read()))['posts'] == []

    phase_inputs = [json.loads(path.read_text())
                    for path in sorted(out.glob('phase-*-inputs.json'))]
    prompt_rows = [row['policy_prompt'] for phase in phase_inputs for row in phase]
    assert prompt_rows and all(row == manifest['policy_prompt'] for row in prompt_rows)
    samples = [row['sample'] for phase in phase_inputs for row in phase]
    assert all(sample['input'] == render_tools_instruction('D') for sample in samples)
    assert all(sample['metadata']['instruction_prompt'] == render_tools_instruction('D')
               for sample in samples)
    assert all(sample['metadata']['completion'] == manifest['completion'] for sample in samples)
    by_team_slot = {}
    for sample in samples:
        metadata = sample['metadata']
        by_team_slot.setdefault((metadata['team'], metadata['slot']), []).append(sample)
    assert all(len(pair) == 2 and pair[0]['input'] == pair[1]['input']
               for pair in by_team_slot.values())


def test_upstream_legacy_prompt_path_is_explicit(tmp_path, monkeypatch):
    import inspect_ai
    from inspect_ai.dataset import Sample
    import messageboardbench.board_task as board_task
    import messageboardbench.task as task_module
    upstream_instruction = render_tools_instruction('A')
    development_ids = ['lcbhard_0', 'lcbhard_1', 'lcbhard_2', 'lcbhard_10']
    monkeypatch.setattr(pilot, 'budget', lambda: {'usage': 0, 'limit': 5, 'limit_remaining': 5})
    monkeypatch.setattr(pilot, 'load_pinned_datasets', lambda splits, revision: {
        split: {task_id: make_sample(task_id) for task_id in development_ids}
        for split in splits})
    monkeypatch.setattr(inspect_ai, 'Task', lambda **kw: SimpleNamespace(**kw))
    monkeypatch.setattr(board_task, 'episode_solver', lambda *values: None)
    monkeypatch.setattr(task_module, 'scratch_scorer', lambda split: None)
    monkeypatch.setattr(inspect_ai, 'eval', lambda tasks, **kwargs: [SimpleNamespace(
        location='mock.eval', status='success', eval=SimpleNamespace(metadata=t.metadata),
        samples=[SimpleNamespace(id=t.dataset[0].id, metadata=t.dataset[0].metadata,
            scores={}, messages=[], model_usage={}, limit=None, error=None)]) for t in tasks])
    monkeypatch.setenv('DOCKER_HOST', pilot.REMOTE_DOCKER_HOST)
    out = tmp_path / 'legacy'
    monkeypatch.setattr('sys.argv', ['board_pilot', '--out', str(out), '--prompt-variant',
                                    'upstream-legacy', '--dataset-revision', REVISION,
                                    '--ids', *development_ids,
                                    '--splits', 'conflicting', 'conflicting', 'conflicting', 'conflicting',
                                    '--execute'])
    pilot.main()
    manifest = json.loads((out / 'manifest.json').read_text())
    assert manifest['policy_prompt']['variant'] == 'upstream-legacy'
    assert manifest['policy_prompt']['rendered_instruction_prompt'] == upstream_instruction
    assert manifest['policy_prompt']['source'].startswith('upstream dataset')
    assert not manifest['confirmatory'] and not manifest['confirmatory_ready']
