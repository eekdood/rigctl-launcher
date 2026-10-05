import hashlib
import io
import json
from pathlib import Path
import tarfile
import zipfile
import pytest
from build_support.release_assets import prepare_release, source_members


def checked(path, data):
    path.write_bytes(data)
    path.with_name(path.name + '.sha256').write_text(f'{hashlib.sha256(data).hexdigest()}  {path.name}\n')


def inputs(root, version='0.1.0', commit='same-commit'):
    root.mkdir()
    for system, machine, label, extension in [('darwin', 'arm64', 'macos-arm64', '.zip'),
            ('windows', 'AMD64', 'windows-x86_64', '.zip'), ('linux', 'x86_64', 'linux-x86_64', '.tar.gz')]:
        label = f'rigctl-launcher-{version}-{label}'
        report = {'application': {'version': version, 'commit': commit},
                  'target': {'os': system, 'architecture': machine}}
        (root / (label + '.inventory.json')).write_text(json.dumps(report))
        checked(root / (label + extension), ('application-' + system).encode())
        upstream = b'identical upstream source archive bytes'
        manifest = {'application': report['application'], 'target': report['target'],
                    'upstream': [{'file': 'upstream/library.tar.gz', 'sha256': hashlib.sha256(upstream).hexdigest()}],
                    'native': [{'directory': 'native/provider', 'source': [{'file': 'patch.diff'}]}]}
        path = root / (label + '-sources.tar.gz')
        with tarfile.open(path, 'w:gz') as archive:
            files = {'application.tar': b'identical tracked snapshot', 'manifest.json': json.dumps(manifest).encode(),
                     'inventory.json': json.dumps(report).encode(), 'upstream/library.tar.gz': upstream,
                     'native/provider/patch.diff': ('patch-' + system).encode(), 'BUILD.md': b'Instructions'}
            for name, data in files.items():
                info = tarfile.TarInfo('rigctl-launcher-sources/' + name)
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
        checked(path, path.read_bytes())
    return root


def test_public_layout_has_one_source_zip_and_combined_checksums(tmp_path):
    source = inputs(tmp_path / 'inputs')
    output = tmp_path / 'public'
    names = prepare_release(source, output, '0.1.0')
    assert names == ['checksums.txt', 'rigctl-launcher-0.1.0-linux-x86_64.tar.gz',
                     'rigctl-launcher-0.1.0-macos-arm64.zip', 'rigctl-launcher-0.1.0-sources.zip',
                     'rigctl-launcher-0.1.0-windows-x86_64.zip']
    for line in (output / 'checksums.txt').read_text().splitlines():
        sha, name = line.split()
        assert hashlib.sha256((output / name).read_bytes()).hexdigest() == sha
    with zipfile.ZipFile(output / 'rigctl-launcher-0.1.0-sources.zip') as archive:
        prefix = 'rigctl-launcher-sources/'
        shared = [name for name in archive.namelist() if name.startswith(prefix + 'shared/')]
        assert len(shared) == 2  # one app snapshot and one shared upstream archive
        index = json.loads(archive.read(prefix + 'index.json'))
        assert len(index) == 3
        for item in index:
            manifest = json.loads(archive.read(prefix + item['manifest']))
            assert archive.read(prefix + manifest['application_source']) == b'identical tracked snapshot'
            record = manifest['upstream'][0]
            assert hashlib.sha256(archive.read(prefix + record['file'])).hexdigest() == record['sha256']
            assert archive.read(prefix + manifest['native'][0]['directory'] + '/patch.diff').startswith(b'patch-')
            assert item['inventory'] in [name.removeprefix(prefix) for name in archive.namelist()]


def test_release_rejects_missing_platforms_mismatched_versions_and_corrupt_downloads(tmp_path):
    root = inputs(tmp_path / 'inputs')
    linux = root / 'rigctl-launcher-0.1.0-linux-x86_64.inventory.json'
    original = linux.read_text()
    linux.unlink()
    with pytest.raises(ValueError, match='all expected platforms'):
        prepare_release(root, tmp_path / 'public', '0.1.0')
    linux.write_text(original)
    with pytest.raises(ValueError, match='version differs'):
        prepare_release(root, tmp_path / 'public', '0.2.0')
    data = json.loads(original)
    data['application']['commit'] = 'different-commit'
    linux.write_text(json.dumps(data))
    with pytest.raises(ValueError, match='one commit'):
        prepare_release(root, tmp_path / 'public', '0.1.0')
    linux.write_text(original)
    next(root.glob('*.zip')).write_bytes(b'tampered download')
    with pytest.raises(ValueError, match='Checksum mismatch'):
        prepare_release(root, tmp_path / 'public', '0.1.0')
    assert not (tmp_path / 'public').exists()


def test_source_archive_paths_and_links_cannot_escape_zip_layout(tmp_path):
    for name, kind in [('rigctl-launcher-sources/../../outside', tarfile.REGTYPE),
                       ('rigctl-launcher-sources/link', tarfile.SYMTYPE)]:
        path = tmp_path / 'unsafe.tar'
        with tarfile.open(path, 'w') as archive:
            info = tarfile.TarInfo(name)
            info.type = kind
            info.linkname = '/outside'
            archive.addfile(info)
        with tarfile.open(path) as archive, pytest.raises(ValueError):
            source_members(archive)
