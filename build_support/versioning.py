"""Generate public application metadata from pyproject.toml."""
import json
from pathlib import Path
import platform
import plistlib
from packaging.version import InvalidVersion, Version
from .inventory import project_version

BUNDLE_IDENTIFIER = 'io.github.eekdood.rigctl-launcher'
DISPLAY_NAME = 'RigCtl-Launcher'


def version_details(root):
    text = project_version(root)
    try:
        parsed = Version(text)
    except InvalidVersion as error:
        raise ValueError('Project version must be a valid Python package version') from error
    if parsed.epoch or len(parsed.release) > 3 or any(part > 65535 for part in parsed.release):
        raise ValueError('Project version must fit three Windows version fields (0–65535)')
    release = (*parsed.release, *(0 for _ in range(3 - len(parsed.release))))
    return {'version': str(parsed), 'numeric_version': '.'.join(map(str, release)),
            'windows_version': (*release, 0), 'bundle_identifier': BUNDLE_IDENTIFIER,
            'display_name': DISPLAY_NAME}


def archive_label(details, system=None, machine=None):
    system = (system or platform.system()).lower()
    machine = (machine or platform.machine()).lower()
    system = {'darwin': 'macos'}.get(system, system)
    machine = {'amd64': 'x86_64', 'aarch64': 'arm64'}.get(machine, machine)
    return f'rigctl-launcher-{details["version"]}-{system}-{machine}'


def verify_metadata(target, details, system=None):
    """Check metadata in the built bundle, including native executable resources."""
    system = (system or platform.system()).lower()
    target = Path(target)
    data_root = target / 'Contents' / 'Resources' if system == 'darwin' else target / '_internal'
    metadata = json.loads((data_root / 'application-metadata.json').read_text())
    expected = {'version': details['version'], 'name': DISPLAY_NAME,
                'bundle_identifier': BUNDLE_IDENTIFIER}
    if metadata != expected:
        raise ValueError('Packaged application metadata differs from project version')
    if system == 'darwin':
        with (target / 'Contents' / 'Info.plist').open('rb') as stream:
            plist = plistlib.load(stream)
        expected = {'CFBundleIdentifier': BUNDLE_IDENTIFIER, 'CFBundleName': DISPLAY_NAME,
                    'CFBundleShortVersionString': details['numeric_version'],
                    'CFBundleVersion': details['numeric_version'],
                    'RigCtlLauncherVersion': details['version']}
        if any(plist.get(key) != value for key, value in expected.items()):
            raise ValueError('macOS bundle metadata differs from project version')
    elif system == 'windows':
        from .inventory import file_version
        expected = '.'.join(map(str, details['windows_version']))
        if file_version(target / 'rigctl-launcher.exe') != expected:
            raise ValueError('Windows executable version differs from project version')


def windows_resource(details):
    values = {'CompanyName': 'RigCtl-Launcher project', 'FileDescription': DISPLAY_NAME,
              'FileVersion': '.'.join(map(str, details['windows_version'])),
              'InternalName': 'rigctl-launcher', 'OriginalFilename': 'rigctl-launcher.exe',
              'ProductName': DISPLAY_NAME, 'ProductVersion': details['version']}
    strings = ',\n'.join(f'StringStruct({key!r}, {value!r})' for key, value in values.items())
    return f'''VSVersionInfo(
 ffi=FixedFileInfo(filevers={details['windows_version']!r}, prodvers={details['windows_version']!r},
 mask=0x3f, flags=0, OS=0x40004, fileType=1, subtype=0, date=(0,0)),
 kids=[StringFileInfo([StringTable('040904b0', [{strings}])]),
 VarFileInfo([VarStruct('Translation', [1033,1200])])])
'''


def write_spec(root, system=None):
    root = Path(root).resolve()
    system = (system or platform.system()).lower()
    details = version_details(root)
    generated = root / 'build' / 'application-metadata'
    generated.mkdir(parents=True, exist_ok=True)
    metadata = generated / 'application-metadata.json'
    metadata.write_text(json.dumps({'version': details['version'], 'name': DISPLAY_NAME,
                                   'bundle_identifier': BUNDLE_IDENTIFIER}, indent=2) + '\n')
    resource = generated / 'windows-version.txt'
    resource.write_text(windows_resource(details))
    plist = {'CFBundleName': DISPLAY_NAME, 'CFBundleDisplayName': DISPLAY_NAME,
             'CFBundleShortVersionString': details['numeric_version'],
             'CFBundleVersion': details['numeric_version'], 'RigCtlLauncherVersion': details['version']}
    text = f'''# Generated from pyproject.toml; source paths stay in ignored build storage.
a = Analysis([{str(root / 'packaging' / 'entrypoint.py')!r}], pathex=[{str(root)!r}],
 binaries=[], datas=[({str(root / 'license.txt')!r}, '.'), ({str(metadata)!r}, '.')],
 hiddenimports=[], hookspath=[{str(root / 'packaging' / 'hooks')!r}],
 hooksconfig={{}}, runtime_hooks=[], excludes=[], noarchive=False, optimize=0)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='rigctl-launcher',
 debug=False, bootloader_ignore_signals=False, strip=False, upx=False, console=False,
 disable_windowed_traceback=False, argv_emulation=False, target_arch=None,
 codesign_identity=None, entitlements_file=None,
 version={str(resource) if system == 'windows' else None!r})
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, upx_exclude=[], name='rigctl-launcher')
'''
    if system == 'darwin':
        text += f'''app = BUNDLE(coll, name='rigctl-launcher.app', icon=None,
 bundle_identifier={BUNDLE_IDENTIFIER!r}, version={details['numeric_version']!r}, info_plist={plist!r})
'''
    spec = root / 'build' / 'rigctl-launcher.spec'
    spec.write_text(text)
    return spec, details
