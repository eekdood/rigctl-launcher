import io
import json
from pathlib import Path
import tarfile
import pytest
from build_support.notices import SourceCache, archive_notices, copy_notice, native_notices


def make_archive(path, files):
    with tarfile.open(path, 'w:gz') as archive:
        for name, data in files.items():
            member = tarfile.TarInfo(name)
            member.size = len(data)
            archive.addfile(member, io.BytesIO(data))


def test_only_legal_files_and_referenced_attributions_are_copied(tmp_path):
    archive = tmp_path / 'source.tar.gz'
    attribution = {'Name': 'Embedded library', 'Version': '2.3', 'Copyright': ['Upstream owner'],
                   'LicenseFile': 'terms.md', 'LicenseId': 'MIT'}
    make_archive(archive, {'vendor/LICENSES/MIT.txt': b'Upstream license text',
                          'vendor/src/library/qt_attribution.json': json.dumps(attribution).encode(),
                          'vendor/src/library/terms.md': b'Copyright upstream owner\nPermission terms',
                          'vendor/src/implementation.cpp': b'Do not copy implementation',
                          'vendor/LICENSES/LicenseRef-Qt-Commercial.txt': b'No commercial license granted'})
    target = tmp_path / 'notices'
    records = archive_notices(archive, target, 'https://example.invalid/matching-version')
    assert (target / 'src/library/terms.md').read_bytes().startswith(b'Copyright')
    assert not (target / 'src/implementation.cpp').exists()
    assert not (target / 'licenses/licenseref-qt-commercial.txt').exists()
    assert len(records) == 2
    assert records[0]['source_archive_sha256']
    assert json.loads((target / 'qt-attributions.json').read_text())[0]['Version'] == '2.3'


def test_missing_attribution_document_fails_the_build(tmp_path):
    archive = tmp_path / 'source.tar.gz'
    make_archive(archive, {'vendor/qt_attribution.json': b'{"LicenseFile":"missing.txt"}',
                          'vendor/LICENSE': b'Generic license does not replace missing notice'})
    with pytest.raises(ValueError, match='Missing upstream attribution'):
        archive_notices(archive, tmp_path / 'legal', 'https://example.invalid')


def test_license_path_cannot_escape_archive_root(tmp_path):
    archive = tmp_path / 'source.tar.gz'
    make_archive(archive, {'vendor/qt_attribution.json': b'{"LicenseFile":"../../outside.txt"}',
                          'vendor/LICENSE': b'License'})
    with pytest.raises(ValueError, match='Missing upstream attribution'):
        archive_notices(archive, tmp_path / 'legal', 'https://example.invalid')


def test_legacy_copyright_bytes_are_preserved(tmp_path):
    records = []
    data = b'Copyright \xa9 original owner'
    copy_notice(data, tmp_path, 'copyright.txt', {}, records)
    assert (tmp_path / 'copyright.txt').read_bytes() == data


def test_unknown_native_provider_does_not_silently_ship_without_notices(tmp_path):
    with pytest.raises(ValueError, match='No supplied license'):
        native_notices({'id': 'unknown', 'provider': 'unsupported'}, [], tmp_path)


def test_notice_downloads_use_allowlisted_https_hosts(tmp_path):
    with pytest.raises(ValueError, match='approved upstream'):
        SourceCache(tmp_path).fetch('http://example.invalid/license')
