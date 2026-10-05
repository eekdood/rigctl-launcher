"""Identify development downloads separately from tagged releases."""
import json
import os
from pathlib import Path
import re
import subprocess


def build_identity(version, commit, environ=None):
    env = os.environ if environ is None else environ
    if not re.fullmatch(r'[0-9a-fA-F]{7,64}', commit):
        raise ValueError('Build requires a hexadecimal Git commit')
    event, ref = env.get('GITHUB_EVENT_NAME'), env.get('GITHUB_REF', '')
    if event == 'push' and ref.startswith('refs/tags/'):
        if ref != 'refs/tags/v' + version:
            raise ValueError('Release tag must match project version')
        return {'kind': 'release', 'name': version}
    if event == 'pull_request':
        number = json.loads(Path(env['GITHUB_EVENT_PATH']).read_text())['number']
        if type(number) is not int or number <= 0:
            raise ValueError('Pull request number must be a positive integer')
        return {'kind': 'pull_request', 'name': f'pr-{number}_{commit[:7].lower()}'}
    return {'kind': 'development', 'name': f'dev_{commit[:7].lower()}'}


def checkout_identity(root, version):
    commit = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=root, capture_output=True,
                            text=True, check=True).stdout.strip()
    return build_identity(version, commit)
