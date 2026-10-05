"""Build and archive on the native OS. Includes application dependencies only."""
import hashlib
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build():
    subprocess.run([
        sys.executable, '-m', 'PyInstaller', '--clean', '--noconfirm',
        '--windowed', '--onedir', '--name', 'rigctl-launcher',
        '--add-data', f'{ROOT / "license.txt"}:.',
        '--paths', str(ROOT), '--specpath', str(ROOT / 'build'),
        str(ROOT / 'packaging' / 'entrypoint.py'),
    ], cwd=ROOT, check=True, env={**os.environ, 'PYINSTALLER_CONFIG_DIR': str(ROOT / 'build' / 'pyinstaller-cache')})
    dist = ROOT / 'dist'
    system = platform.system().lower()
    machine = platform.machine().lower()
    label = f'rigctl-launcher-{system}-{machine}'
    archives = ROOT / 'artifacts' / 'packages'
    archives.mkdir(parents=True, exist_ok=True)
    if system == 'darwin':
        target = dist / 'rigctl-launcher.app'
        executable = target / 'Contents' / 'MacOS' / 'rigctl-launcher'
    else:
        target = dist / 'rigctl-launcher'
        executable = target / ('rigctl-launcher.exe' if system == 'windows' else 'rigctl-launcher')
    # No serial discovery, real user configuration or radio processes in this test.
    subprocess.run([str(executable), '--smoke-test'], cwd=ROOT, check=True, timeout=30)
    if system == 'darwin':
        archive = archives / f'{label}.zip'
        subprocess.run(['ditto', '-c', '-k', '--keepParent', str(target), str(archive)], check=True)
    else:
        archive = Path(shutil.make_archive(str(archives / label),
                       'zip' if system == 'windows' else 'gztar',
                       root_dir=dist, base_dir=target.name))
    with archive.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    archive.with_name(archive.name + '.sha256').write_text(f'{digest}  {archive.name}\n')
    print(f'Built and smoke-tested {archive.name}')


if __name__ == '__main__':
    build()
