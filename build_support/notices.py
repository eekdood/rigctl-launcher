"""Collect version-matched upstream notices; never extract upstream source trees."""
import hashlib
from importlib import metadata
import json
from pathlib import Path, PurePosixPath
import posixpath
import re
import shutil
import sys
import tarfile
import urllib.request
import zipfile
from xml.etree import ElementTree

LEGAL = re.compile(r'^(licen[sc]e|copying|copyright|notice)([._-].*)?$', re.I)


class SourceCache:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def fetch(self, url):
        if not url.startswith(('https://codeload.github.com/', 'https://raw.githubusercontent.com/', 'https://visualstudio.microsoft.com/', 'https://sourceware.org/pub/bzip2/')):
            raise ValueError('Notice downloads must use an approved upstream HTTPS host')
        path = self.directory / (hashlib.sha256(url.encode()).hexdigest() + ('.tar.gz' if '/tar.gz/' in url else '.txt'))
        if not path.exists():
            temporary = path.with_suffix('.partial')
            try:
                print(f'Collecting upstream notices: {url}', flush=True)
                with urllib.request.urlopen(url, timeout=60) as response, temporary.open('wb') as output:
                    shutil.copyfileobj(response, output)
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)
        return path


def slug(value):
    return re.sub(r'[^a-z0-9._-]+', '-', value.lower()).strip('-')


def copy_notice(data, directory, name, provenance, records):
    if not data or len(data) > 5_000_000:
        raise ValueError(f'Invalid license document: {name}')
    # Preserve upstream bytes, including legacy encodings and copyright marks.
    path = directory / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    records.append({'path': path.relative_to(directory).as_posix(), 'sha256': hashlib.sha256(data).hexdigest(), **provenance})


def archive_notices(archive_path, directory, url):
    """Read legal files directly from tar members, never extract arbitrary members."""
    records, attributions = [], []
    with archive_path.open('rb') as stream:
        archive_hash = hashlib.file_digest(stream, 'sha256').hexdigest()
    with tarfile.open(archive_path) as archive:
        members = {member.name: member for member in archive.getmembers() if member.isfile()}
        selected = {name for name in members if LEGAL.fullmatch(PurePosixPath(name).name) or '/LICENSES/' in name
                    or (name.count('/') == 1 and PurePosixPath(name).name.lower().startswith('readme'))}
        roots = {name.split('/')[0] for name in members}
        if len(roots) != 1:
            raise ValueError('Upstream archive must have a single root directory')
        root = next(iter(roots))
        for name, member in members.items():
            if not name.endswith('/qt_attribution.json'):
                continue
            entries = json.loads(archive.extractfile(member).read(), strict=False)
            if isinstance(entries, dict):
                entries = [entries]
            for entry in entries:
                attributions.append({'upstream_path': name.split('/', 1)[1], **entry})
                license_files = entry.get('LicenseFile', [])
                if isinstance(license_files, str):
                    license_files = [license_files]
                for license_file in license_files:
                    candidate = posixpath.normpath(posixpath.join(posixpath.dirname(name), license_file))
                    if not candidate.startswith(root + '/') or candidate not in members:
                        raise ValueError(f'Missing upstream attribution license: {name}: {license_file}')
                    selected.add(candidate)
        for name in sorted(selected):
            relative = PurePosixPath(name).relative_to(root)
            if '..' in relative.parts or relative.is_absolute():
                raise ValueError('Unsafe upstream license path')
            # Upstream commercial alternatives do not grant a commercial license.
            if 'licenseref-qt-commercial' in str(relative).lower():
                continue
            data = archive.extractfile(members[name]).read()
            copy_notice(data, directory, relative.as_posix().lower(),
                        {'upstream_url': url, 'upstream_path': relative.as_posix(), 'source_archive_sha256': archive_hash}, records)
    if not records:
        raise ValueError(f'No legal documents in upstream archive: {url}')
    if attributions:
        (directory / 'qt-attributions.json').write_text(json.dumps(attributions, indent=2, ensure_ascii=False) + '\n')
    return records


def upstream_archive(cache, directory, project, version):
    url = f'https://codeload.github.com/{project}/tar.gz/refs/tags/v{version}'
    return archive_notices(cache.fetch(url), directory, url)


def native_notices(component, entries, directory):
    records = []
    if component['provider'] == 'homebrew':
        candidates = []
        for _, source, _ in entries:
            parts = Path(source).resolve().parts
            if 'Cellar' not in parts:
                continue
            index = parts.index('Cellar')
            if tuple(parts[index + 1:index + 3]) == (component['name'], component['version']):
                root = Path(*parts[:index + 3])
                candidates = [path for path in root.rglob('*') if path.is_file() and LEGAL.fullmatch(path.name)]
                break
        for path in sorted(candidates):
            copy_notice(path.read_bytes(), directory, path.relative_to(root).as_posix().lower(),
                        {'provider': 'homebrew', 'package': component['name'], 'version': component['version']}, records)
    elif component['provider'] == 'dpkg':
        package = component['name'].split(':')[0]
        path = Path('/usr/share/doc') / package / 'copyright'
        if path.is_file():
            copy_notice(path.read_bytes(), directory, 'copyright.txt',
                        {'provider': 'dpkg', 'package': component['name'], 'version': component['version']}, records)
            for common in Path('/usr/share/common-licenses').iterdir():
                if common.is_file():
                    copy_notice(common.read_bytes(), directory, 'common-licenses/' + common.name.lower() + '.txt',
                                {'provider': 'debian-common-licenses'}, records)
    if not records:
        raise ValueError(f'No supplied license notices for native provider: {component["id"]}')
    return records


def collect_notices(report, entries, destination, cache):
    """Cover collected providers plus conservative catalogs of embedded code."""
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    licenses = destination / 'licenses'
    licenses.mkdir()
    catalog = {}
    versions = {re.sub(r'[-_.]+', '-', c['name']).lower(): c['version'] for c in report['components']}
    python_version, qt_version = report['runtime']['python'], report['runtime']['qt']
    catalog['cpython'] = upstream_archive(cache, licenses / 'cpython', 'python/cpython', python_version)
    pyside_version = versions.get('pyside6-essentials')
    if not pyside_version:
        raise ValueError('Missing collected PySide6 runtime')
    catalog['pyside-shiboken'] = upstream_archive(cache, licenses / 'pyside-shiboken', 'pyside/pyside-setup', pyside_version)
    # Desktop plugins are retained. PDF and virtual-keyboard plugins are excluded
    # by the QtGui hook, avoiding their unrelated runtime and attribution trees.
    modules = {'qtbase'}
    names = ' '.join(file['name'].lower() for file in report['collected_files'])
    if 'svg' in names:
        modules.add('qtsvg')
    if any(part in names for part in ('qwebp', 'qtiff', 'qicns', 'qwbmp', 'qtga')):
        modules.add('qtimageformats')
    if 'wayland' in names:
        modules.add('qtwayland')
    if any(part in names for part in ('qtpdf', 'qt6pdf', 'virtualkeyboard')):
        raise ValueError('Unexpected PDF/virtual-keyboard runtime; extend notice coverage before shipping')
    for module in sorted(modules):
        catalog[module] = upstream_archive(cache, licenses / module, f'qt/{module}', qt_version)
    catalog['pyserial'] = upstream_archive(cache, licenses / 'pyserial', 'pyserial/pyserial', versions['pyserial'])
    if report['target']['os'] == 'windows':
        # CPython's Windows extension modules statically contain these externals.
        python_url = f'https://codeload.github.com/python/cpython/tar.gz/refs/tags/v{python_version}'
        with tarfile.open(cache.fetch(python_url)) as archive:
            props = next(m for m in archive.getmembers() if m.name.endswith('/PCbuild/python.props'))
            xml = ElementTree.fromstring(archive.extractfile(props).read())
        props_text = ' '.join(node.text or '' for node in xml.iter())
        for marker, source_name, project in [('_bz2', 'bzip2', None), ('_lzma', 'xz', 'tukaani-project/xz'), ('zlib', 'zlib', 'madler/zlib')]:
            if marker not in names:
                continue
            match = re.search(re.escape(source_name) + r'-(\d+\.\d+\.\d+)', props_text)
            if not match:
                raise ValueError(f'CPython build manifest lacks {source_name} version')
            version = match.group(1)
            name = source_name + '-' + version
            url = (f'https://sourceware.org/pub/bzip2/bzip2-{version}.tar.gz' if project is None
                   else f'https://codeload.github.com/{project}/tar.gz/refs/tags/v{version}')
            catalog[name] = archive_notices(cache.fetch(url), licenses / name, url)
            report.setdefault('embedded_runtime_dependencies', []).append({'name': source_name, 'version': version,
                      'version_source': 'CPython Windows build manifest', 'notice_catalog': name})

        # CPython maintains Windows-specific external sources and build patches.
        # Preserve these alongside upstream originals in the source downloads.
        externals = list(report.get('embedded_runtime_dependencies', []))
        externals += [{'name': 'openssl' if c['name'] == 'openssl' else 'libffi',
                       'version': '.'.join(c['version'].split('.')[:3]) if c['name'] == 'openssl' else
                       re.search(r'libffi-(\d+\.\d+\.\d+)', props_text).group(1)}
                      for c in report['components'] if c['provider'] == 'windows-native-library']
        for external in externals:
            tag = external['name'] + '-' + external['version']
            name = 'cpython-external-' + tag
            url = f'https://codeload.github.com/python/cpython-source-deps/tar.gz/refs/tags/{tag}'
            catalog[name] = archive_notices(cache.fetch(url), licenses / name, url)

    covered = []
    for component in report['components']:
        provider = component['provider']
        key = re.sub(r'[-_.]+', '-', component['name']).lower()
        if provider in {'homebrew', 'dpkg'}:
            name = slug(component['id'])
            catalog[name] = native_notices(component, entries, licenses / name)
            component['notice_catalog'] = name
        elif provider == 'project':
            component['notice_catalog'] = 'license.txt'
        elif provider == 'python-runtime':
            component['notice_catalog'] = 'cpython'
        elif provider == 'python-distribution':
            if key in {'pyside6', 'pyside6-essentials', 'pyside6-addons', 'shiboken6'}:
                component['notice_catalog'] = 'pyside-shiboken'
            elif key == 'pyserial':
                component['notice_catalog'] = 'pyserial'
            elif key == 'pyinstaller':
                dist = metadata.distribution('PyInstaller')
                for file in dist.files or []:
                    if str(file).endswith('/COPYING.txt'):
                        catalog['pyinstaller'] = []
                        copy_notice(Path(dist.locate_file(file)).read_bytes(), licenses / 'pyinstaller', 'copying.txt',
                                    {'provider': 'python-distribution', 'version': dist.version}, catalog['pyinstaller'])
                component['notice_catalog'] = 'pyinstaller'
            else:
                raise ValueError(f'No notice policy for collected distribution: {key}')
        elif provider == 'windows-native-library':
            version = component['version']
            if key == 'openssl':
                if not version:
                    raise ValueError('OpenSSL DLL has no version resource; provide version-matched notices before shipping')
                version = '.'.join(version.split('.')[:3])
                name = 'openssl-' + version
                url = f'https://codeload.github.com/openssl/openssl/tar.gz/refs/tags/openssl-{version}'
            elif key == 'libffi':
                url = f'https://codeload.github.com/python/cpython/tar.gz/refs/tags/v{python_version}'
                with tarfile.open(cache.fetch(url)) as archive:
                    props = next(m for m in archive.getmembers() if m.name.endswith('/PCbuild/python.props'))
                    xml = ElementTree.fromstring(archive.extractfile(props).read())
                props_text = ' '.join(node.text or '' for node in xml.iter())
                match = re.search(r'libffi-(\d+\.\d+\.\d+)', props_text)
                if not match:
                    raise ValueError('CPython build manifest lacks the libffi version')
                version = match.group(1)
                name = 'libffi-' + version
                url = f'https://codeload.github.com/libffi/libffi/tar.gz/refs/tags/v{version}'
                component['notice_source_version'] = version
                component['notice_version_source'] = 'CPython Windows build manifest'
            else:
                raise ValueError(f'Unknown Windows native library: {key}')
            if name not in catalog:
                catalog[name] = archive_notices(cache.fetch(url), licenses / name, url)
            component['notice_catalog'] = name
        elif provider == 'windows-version-resource':
            # Microsoft runtime licenses are supplied by Visual Studio/Windows SDK,
            # not the Python or Qt open-source licenses.
            name = 'microsoft-runtime'
            if name not in catalog:
                catalog[name] = []
                url = 'https://visualstudio.microsoft.com/wp-content/uploads/2021/09/Visual-C-Runtime-2015-2022-License-1.docx'
                original = cache.fetch(url).read_bytes()
                copy_notice(original, licenses / name, 'visual-cpp-runtime-terms.docx', {'upstream_url': url}, catalog[name])
                with zipfile.ZipFile(cache.fetch(url)) as document:
                    xml = ElementTree.fromstring(document.read('word/document.xml'))
                paragraphs = [''.join(node.itertext()) for node in xml.iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p')]
                copy_notice(('\n'.join(paragraphs) + '\n').encode(), licenses / name, 'visual-cpp-runtime-terms.txt',
                            {'upstream_url': url, 'conversion': 'DOCX paragraph text'}, catalog[name])
                url = 'https://raw.githubusercontent.com/microsoft/win32metadata/bd964b20fd0996865afd827ba0d6e712f69712a6/licenses/sdk_license.txt'
                copy_notice(cache.fetch(url).read_bytes(), licenses / name, 'windows-sdk-terms.txt',
                            {'upstream_url': url}, catalog[name])
            component['notice_catalog'] = name
        else:
            raise ValueError(f'Unresolved native license provider: {component["id"]}')
        covered.append(f'- {component["name"]} {component["version"] or "version unavailable"}: {component["notice_catalog"]}')
    report['notice_catalogs'] = catalog
    text = ['RigCtl-Launcher third-party notices', '',
            'Component versions and exact collected files are recorded in inventory.json.',
            'Upstream copyrights and license statements are preserved under licenses/.',
            'Qt catalogs conservatively include notices from the matching source modules;',
            'some catalog entries may describe code not used by this build.',
            'Matching source archives and build instructions accompany the release downloads:',
            'https://github.com/eekdood/rigctl-launcher/releases', '',
            'Hamlib is neither installed nor bundled by this application.', '', *covered, '',
            'PyInstaller permits distribution of generated applications under their own licenses;',
            'its supplied exception is retained for reference.', '']
    (destination / 'third-party-notices.txt').write_text('\n'.join(text))
    (destination / 'inventory.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
