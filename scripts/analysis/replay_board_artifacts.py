"""Replay final artifacts in Docker without networking or host mounts; no paid calls.

Host code only copies artifact bytes. Each artifact executes in a separate container.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile
import uuid


def replay(files, destination, image):
    destination.mkdir(parents=True, exist_ok=False)
    for name, content in files.items():
        (destination / name).write_bytes(content)
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode='w') as tar:
        directory = tarfile.TarInfo('workspace')
        directory.type = tarfile.DIRTYPE
        directory.mode = 0o755
        tar.addfile(directory)
        for name, content in files.items():
            info = tarfile.TarInfo('workspace/' + name)
            info.size = len(content)
            info.mode = 0o444
            tar.addfile(info, io.BytesIO(content))
    name = 'board-artifact-validation-' + uuid.uuid4().hex[:12]
    create = ['docker', 'create', '--name', name, '--network', 'none', '--memory', '512m',
              '--pids-limit', '64', '--cap-drop', 'ALL', '--security-opt',
              'no-new-privileges', '--user', '65534:65534', '--workdir', '/workspace',
              image, 'python3', '-B', '/workspace/probe.py']
    subprocess.run(create, check=True, capture_output=True)
    try:
        subprocess.run(['docker', 'cp', '-', name + ':/'], input=archive.getvalue(), check=True, capture_output=True)
        configuration = json.loads(subprocess.check_output(['docker', 'inspect', name]))[0]
        assert configuration['HostConfig']['NetworkMode'] == 'none'
        assert not configuration['Mounts']
        try:
            result = subprocess.run(['docker', 'start', '-a', name], capture_output=True, timeout=120)
            timed_out = False
        except subprocess.TimeoutExpired as error:
            result = subprocess.CompletedProcess([], 124, error.stdout or b'', error.stderr or b'')
            timed_out = True
        state = json.loads(subprocess.check_output(['docker', 'inspect', name]))[0]['State']
        (destination / 'stdout.txt').write_bytes(result.stdout)
        (destination / 'stderr.txt').write_bytes(result.stderr)
        record = {'create_command': create, 'network_mode': configuration['HostConfig']['NetworkMode'],
                  'mounts': configuration['Mounts'], 'image_id': configuration['Image'],
                  'docker_start_exit_code': result.returncode, 'container_exit_code': state['ExitCode'],
                  'timed_out': timed_out, 'files_sha256': {k: hashlib.sha256(v).hexdigest() for k, v in files.items()}}
        (destination / 'result.json').write_text(json.dumps(record, indent=2) + '\n')
        return record
    finally:
        subprocess.run(['docker', 'rm', '-f', name], capture_output=True, check=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run', type=Path, required=True)
    p.add_argument('--export', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--image', default='aisiuk/inspect-tool-support')
    args = p.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    inputs = {x['sample']['metadata']['episode_id']: x['sample']['metadata']
              for path in args.run.glob('phase-*-inputs.json') for x in json.loads(path.read_text())}
    rows = json.loads((args.export / 'episodes.json').read_text())
    records = []
    for row in rows:
        final = json.loads((args.export / row['report_directory'] / 'final-artifacts.json').read_text())
        artifacts = final.get('submitted_artifacts', {})
        if not isinstance(artifacts.get('func.py'), str):
            records.append({'episode_id': row['episode_id'], 'skipped': 'No captured source'})
            continue
        meta = inputs[row['episode_id']]
        test = artifacts.get('test.py')
        if not test:
            raise ValueError('Missing captured test.py: ' + row['episode_id'])
        # Execute the exact captured test file. runpy preserves filename and __main__.
        probe = "import runpy\nrunpy.run_path('/workspace/test.py', run_name='__main__')\nprint('REPLAY_COMPLETED')\n"
        files = {'func.py': artifacts['func.py'].encode(), 'test.py': test.encode(), 'probe.py': probe.encode()}
        result = replay(files, args.out / row['report_directory'], args.image)
        records.append({'episode_id': row['episode_id'], 'task_id': row['task_id'], 'condition': row['condition'],
                        'split': row['split'], 'reported_score': row['score'], **result})
        print(json.dumps({'episode_id': row['episode_id'], 'container_exit_code': result['container_exit_code']}), flush=True)
    (args.out / 'summary.json').write_text(json.dumps(records, indent=2) + '\n')
