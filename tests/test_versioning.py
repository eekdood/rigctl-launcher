import ast
import json
import plistlib
from pathlib import Path
import sys
import pytest
from build_support.versioning import (BUNDLE_IDENTIFIER, DISPLAY_NAME, archive_label,
                                     version_details, windows_resource, write_spec, verify_metadata)
from rigctl_launcher.version import application_version


def project(tmp_path, version='0.1.0'):
    (tmp_path / 'pyproject.toml').write_text(f'[project]\nversion="{version}"\n')
    return tmp_path


def test_one_version_drives_all_platform_archive_names(tmp_path):
    details = version_details(project(tmp_path, '1.2.3rc1'))
    assert details['numeric_version'] == '1.2.3'
    assert details['windows_version'] == (1, 2, 3, 0)
    assert archive_label(details, 'Darwin', 'aarch64') == 'rigctl-launcher-1.2.3rc1-macos-arm64'
    assert archive_label(details, 'Windows', 'AMD64') == 'rigctl-launcher-1.2.3rc1-windows-x86_64'
    assert archive_label(details, 'Linux', 'x86_64') == 'rigctl-launcher-1.2.3rc1-linux-x86_64'


@pytest.mark.parametrize('version', ['bad version', '1!1.0', '1.2.3.4', '65536.0.0'])
def test_invalid_native_version_fields_fail_before_build(tmp_path, version):
    with pytest.raises(ValueError):
        version_details(project(tmp_path, version))


def test_specs_have_native_metadata_and_public_json_has_no_installation_paths(tmp_path):
    project(tmp_path)
    for system in ('darwin', 'windows', 'linux'):
        spec, details = write_spec(tmp_path, system)
        ast.parse(spec.read_text())
        data = (tmp_path / 'build/application-metadata/application-metadata.json').read_text()
        assert str(tmp_path) not in data
        assert json.loads(data) == {'version': '0.1.0', 'name': DISPLAY_NAME,
                                    'bundle_identifier': BUNDLE_IDENTIFIER}
        assert ('app = BUNDLE' in spec.read_text()) == (system == 'darwin')
        tree = ast.parse(windows_resource(details))
        fixed = tree.body[0].value.keywords[0].value
        fields = {node.arg: ast.literal_eval(node.value) for node in fixed.keywords}
        assert fields['filevers'] == fields['prodvers'] == (0, 1, 0, 0)


def test_built_macos_metadata_is_verified_and_stale_versions_rejected(tmp_path):
    details = version_details(project(tmp_path))
    target = tmp_path / 'app'
    resources = target / 'Contents/Resources'
    resources.mkdir(parents=True)
    (resources / 'application-metadata.json').write_text(json.dumps({
        'version': details['version'], 'name': DISPLAY_NAME, 'bundle_identifier': BUNDLE_IDENTIFIER}))
    plist = {'CFBundleIdentifier': BUNDLE_IDENTIFIER, 'CFBundleName': DISPLAY_NAME,
             'CFBundleShortVersionString': '0.1.0', 'CFBundleVersion': '0.1.0',
             'RigCtlLauncherVersion': '0.1.0'}
    path = target / 'Contents/Info.plist'
    path.write_bytes(plistlib.dumps(plist))
    verify_metadata(target, details, 'darwin')
    plist['CFBundleVersion'] = '0.0.0'
    path.write_bytes(plistlib.dumps(plist))
    with pytest.raises(ValueError, match='macOS bundle'):
        verify_metadata(target, details, 'darwin')


def test_runtime_uses_only_packaged_public_version_when_frozen(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, '_MEIPASS', str(tmp_path), raising=False)
    path = tmp_path / 'application-metadata.json'
    path.write_text('{"version":"1.2.3"}')
    assert application_version() == '1.2.3'
    path.write_text('{"version":null}')
    with pytest.raises(ValueError, match='Invalid packaged'):
        application_version()
    path.unlink()
    with pytest.raises(FileNotFoundError):
        application_version()


def test_source_runtime_version_matches_project():
    root = Path(__file__).resolve().parents[1]
    assert application_version() == version_details(root)['version']
