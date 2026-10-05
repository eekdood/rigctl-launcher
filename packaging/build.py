"""Build and archive on the native OS. Includes application dependencies only."""
import hashlib
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from build_support.inventory import write_inventory, collected_entries
from build_support.notices import SourceCache, collect_notices


def build():
    subprocess.run([
        sys.executable, '-m', 'PyInstaller', '--clean', '--noconfirm',
        '--windowed', '--onedir', '--name', 'rigctl-launcher',
        '--additional-hooks-dir', str(ROOT / 'packaging' / 'hooks'),
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
        # Synced folders can add Finder metadata to generated bundles.
        subprocess.run(['xattr', '-cr', str(target)], check=True)
        subprocess.run(['codesign', '--verify', '--deep', '--strict', str(target)], check=True)
    inventory_path = archives / f'{label}.inventory.json'
    report = write_inventory(target, ROOT / 'build' / 'rigctl-launcher', ROOT, inventory_path)
    staging = ROOT / 'build' / 'release-layout' / 'rigctl-launcher'
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    collect_notices(report, collected_entries(ROOT / 'build' / 'rigctl-launcher'), staging, SourceCache(ROOT / 'build' / 'notice-cache'))
    shutil.copy2(staging / 'inventory.json', inventory_path)
    shutil.copy2(ROOT / 'license.txt', staging / 'license.txt')
    shutil.copy2(ROOT / 'readme.md', staging / 'readme.md')
    shutil.copytree(target, staging / target.name, symlinks=True)
    if system == 'darwin':
        archive = archives / f'{label}.zip'
        subprocess.run(['ditto', '-c', '-k', '--norsrc', '--noextattr', '--keepParent', str(staging), str(archive)], check=True)
    else:
        archive = Path(shutil.make_archive(str(archives / label),
                       'zip' if system == 'windows' else 'gztar',
                       root_dir=staging.parent, base_dir=staging.name))
    with archive.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    archive.with_name(archive.name + '.sha256').write_text(f'{digest}  {archive.name}\n')
    print(f'Built and smoke-tested {archive.name}')


if __name__ == '__main__':
    build()
