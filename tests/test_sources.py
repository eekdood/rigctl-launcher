import hashlib
import io
import json
from pathlib import Path
import tarfile
import pytest
from build_support.sources import build_sources, debian_sources, homebrew_sources


def fixture_archive(path):
    with tarfile.open(path, 'w:gz') as archive:
        data = b'complete upstream implementation'
        member = tarfile.TarInfo('upstream/source.c')
        member.size = len(data)
        archive.addfile(member, io.BytesIO(data))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_source_bundle_preserves_exact_notice_archive_and_tracked_snapshot(tmp_path, monkeypatch):
    from types import SimpleNamespace
    source = tmp_path / 'source.tar.gz'
    sha = fixture_archive(source)
    (tmp_path / 'build').mkdir()
    (tmp_path / 'packaging').mkdir()
    (tmp_path / 'packaging/source-build.md').write_text('Build instructions')
    (tmp_path / 'pyproject.toml').write_text('[project]\nversion="0.1.0"')
    (tmp_path / 'settings.json').write_text('private local configuration')
    def run(args, **kwargs):
        assert args[:3] == ['git', 'archive', '--format=tar']
        assert 'shell' not in kwargs and args[-1] == 'reviewed-commit'
        Path(args[4]).write_bytes(b'tracked application snapshot')
    monkeypatch.setattr('build_support.sources.subprocess.run', run)
    report = {'application': {'commit': 'reviewed-commit'}, 'target': {'os': 'test'},
              'components': [], 'notice_catalogs': {'qtbase': [{
              'upstream_url': 'https://example.invalid/qtbase', 'source_archive_sha256': sha}]}}
    output = tmp_path / 'sources.tar.gz'
    cache = SimpleNamespace(fetch=lambda url: source)
    build_sources(report, [], tmp_path, output, cache)
    with tarfile.open(output) as archive:
        names = archive.getnames()
        assert not any('settings.json' in name for name in names)
        manifest = json.load(archive.extractfile('rigctl-launcher-sources/manifest.json'))
        record = manifest['upstream'][0]
        assert archive.extractfile('rigctl-launcher-sources/' + record['file']).read() == source.read_bytes()
        assert record['sha256'] == sha
    report['notice_catalogs']['qtbase'][0]['source_archive_sha256'] = 'wrong'
    with pytest.raises(ValueError, match='differs from notice'):
        build_sources(report, [], tmp_path, output, cache)


def test_homebrew_uses_installed_recipe_and_retains_patches(tmp_path, monkeypatch):
    root = tmp_path / 'Cellar/lib/1.2'
    (root / '.brew').mkdir(parents=True)
    library = root / 'lib.dylib'
    library.touch()
    sha = 'a' * 64
    recipe = f'url "https://example.invalid/lib.tar.gz"\nsha256 "{sha}"\npatch :DATA\n__END__\nactual patch\n'
    (root / '.brew/lib.rb').write_text(recipe)
    cached = tmp_path / 'cache'
    cached.write_bytes(b'source archive')
    monkeypatch.setattr('build_support.sources.download', lambda url, path, expected: cached)
    target = tmp_path / 'result'
    target.mkdir()
    records = homebrew_sources({'id': 'lib', 'name': 'lib', 'version': '1.2'},
        [('lib', str(library), 'BINARY')], target, tmp_path)
    assert (target / 'lib.rb').read_text() == recipe
    assert records[0]['sha256'] == sha
    (root / '.brew/lib.rb').write_text('url "https://example.invalid/unpinned"')
    with pytest.raises(ValueError, match='incomplete'):
        homebrew_sources({'id': 'lib', 'name': 'lib', 'version': '1.2'},
            [('lib', str(library), 'BINARY')], target, tmp_path)


def test_debian_source_download_uses_exact_source_version_and_verifies_patches(tmp_path, monkeypatch):
    from types import SimpleNamespace
    data = b'provider patched sources'
    sha = hashlib.sha256(data).hexdigest()
    commands = []
    def run(args, **kwargs):
        commands.append(args)
        if args[0] == 'dpkg-query':
            return SimpleNamespace(stdout='source-name\t1.2-ubuntu3')
        (tmp_path / 'source.orig.tar.gz').write_bytes(data)
        (tmp_path / 'source.dsc').write_text(f'Checksums-Sha256:\n {sha} {len(data)} source.orig.tar.gz\n')
    monkeypatch.setattr('build_support.sources.subprocess.run', run)
    result = debian_sources({'name': 'binary:amd64'}, tmp_path)
    assert result['package'] == 'source-name' and result['version'] == '1.2-ubuntu3'
    assert commands[1][-1] == 'source-name=1.2-ubuntu3'
    assert '--download-only' in commands[1]
    (tmp_path / 'source.orig.tar.gz').write_bytes(b'tampered')
    original = run
    monkeypatch.setattr('build_support.sources.subprocess.run', lambda args, **kw:
        original(args, **kw) if args[0] == 'dpkg-query' else None)
    with pytest.raises(ValueError, match='checksum mismatch'):
        debian_sources({'name': 'binary:amd64'}, tmp_path)
