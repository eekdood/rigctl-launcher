import json
from pathlib import Path
import pytest
from build_support.inventory import artifact_files, collected_entries, describe_sources, native_provider


def test_collected_records_use_tags_not_fixed_pyinstaller_offsets(tmp_path):
    source = tmp_path / 'module.py'
    source.write_text('pass')
    entry = ('module', str(source), 'PYMODULE')
    (tmp_path / 'Analysis-00.toc').write_text(repr(([entry], [entry], [('link', 'relative-target', 'SYMLINK')])))
    assert collected_entries(tmp_path) == [entry]
    with pytest.raises(ValueError, match='No PyInstaller'):
        collected_entries(tmp_path / 'missing')


def test_native_provider_reads_homebrew_version_without_serial_probes(tmp_path):
    path = tmp_path / 'Cellar' / 'compression' / '1.2.3_1' / 'lib' / 'library.dylib'
    path.parent.mkdir(parents=True)
    path.touch()
    assert native_provider(path) == {'name': 'compression', 'version': '1.2.3_1', 'provider': 'homebrew'}


def test_report_excludes_private_source_paths_and_marks_unknowns(tmp_path):
    project = tmp_path / 'private-owner' / 'project'
    project.mkdir(parents=True)
    (project / 'pyproject.toml').write_text('[project]\nversion="0.1.0"\n')
    app = project / 'main.py'
    app.touch()
    dependency = tmp_path / 'private-owner' / 'installed.py'
    dependency.touch()
    unknown = tmp_path / 'unknown.so'
    unknown.touch()
    components, files = describe_sources([
        ('app', str(app), 'PYMODULE'), ('dependency', str(dependency), 'PYMODULE'),
        ('unknown.so', str(unknown), 'BINARY')],
        {dependency.resolve(): 'dependency'}, {'dependency': {'name': 'Dependency', 'version': '2.0'}},
        project, python_root=tmp_path / 'python', provider=lambda path: None)
    output = json.dumps([components, files])
    assert 'private-owner' not in output and str(tmp_path) not in output
    assert any(c['name'] == 'Dependency' and c['version'] == '2.0' for c in components)
    assert any(c['provider'] == 'unresolved-native' and c['version'] is None for c in components)


def test_artifact_hashes_and_symlinks_are_verifiable(tmp_path):
    import hashlib
    target = tmp_path / 'application'
    target.mkdir()
    (target / 'file').write_bytes(b'actual packaged bytes')
    records = artifact_files(target)
    assert records[0]['sha256'] == hashlib.sha256(b'actual packaged bytes').hexdigest()
    try:
        (target / 'alias').symlink_to('file')
    except OSError:
        pytest.skip('Account lacks symlink privilege')
    assert {'path': 'alias', 'symlink': 'file'} in artifact_files(target)
    (target / 'outside').symlink_to('../secret')
    with pytest.raises(ValueError, match='leaves the application'):
        artifact_files(target)
