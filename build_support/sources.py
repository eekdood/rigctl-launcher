"""Create source-download assets from the inventory, including provider recipes."""
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile
import urllib.parse
import urllib.request

from .notices import slug


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def download(url, path, expected):
    """Provider URLs must identify bytes by SHA-256; never run downloaded code."""
    if urllib.parse.urlparse(url).scheme not in {'https', 'http'}:
        raise ValueError('Unsupported source download URL')
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or digest(path) != expected:
        partial = path.with_suffix('.partial')
        try:
            with urllib.request.urlopen(url, timeout=60) as response, partial.open('wb') as stream:
                shutil.copyfileobj(response, stream)
            if digest(partial) != expected:
                raise ValueError(f'Source checksum mismatch: {url}')
            partial.replace(path)
        finally:
            partial.unlink(missing_ok=True)
    return path


def homebrew_sources(component, entries, target, cache):
    roots = []
    for _, source, _ in entries:
        parts = Path(source).resolve().parts
        if 'Cellar' in parts:
            index = parts.index('Cellar')
            if tuple(parts[index + 1:index + 3]) == (component['name'], component['version']):
                roots.append(Path(*parts[:index + 3]))
    if not roots:
        raise ValueError(f'Missing installed Homebrew recipe: {component["id"]}')
    recipe = next(iter((roots[0] / '.brew').glob('*.rb')), None)
    if recipe is None:
        raise ValueError('Installed Homebrew formula is unavailable')
    text = recipe.read_text()
    # Fail on patches instead of silently losing them. Inline patches are in the
    # recipe; external patch/resource URL+SHA pairs below are preserved as well.
    pairs = re.findall(r'^\s*url "([^"\n]+)"(?:(?!^\s*url ).)*?^\s*sha256 "([0-9a-f]{64})"', text, re.M | re.S)
    if not pairs or 'patch :DATA' in text and '__END__' not in text:
        raise ValueError('Homebrew recipe source/patch metadata is incomplete')
    if re.search(r'patch do', text) and len(pairs) < 2:
        raise ValueError('External Homebrew patch has no pinned URL/checksum')
    shutil.copyfile(recipe, target / recipe.name)
    if (roots[0] / 'INSTALL_RECEIPT.json').exists():
        receipt = json.loads((roots[0] / 'INSTALL_RECEIPT.json').read_text())
        # Public build options only; installed receipts can contain local paths.
        (target / 'build-options.json').write_text(json.dumps({key: receipt.get(key) for key in
            ('used_options', 'built_as_bottle', 'poured_from_bottle', 'compiler')}, indent=2) + '\n')
    records = []
    for index, (url, sha) in enumerate(pairs):
        name = f'{index}-' + Path(urllib.parse.urlparse(url).path).name
        cached = download(url, Path(cache) / sha, sha)
        shutil.copyfile(cached, target / name)
        records.append({'file': name, 'url': url, 'sha256': sha})
    return records


def debian_sources(component, target):
    """APT preserves exact distro patches, source control file and build rules."""
    result = subprocess.run(['dpkg-query', '-W', '-f=${source:Package}\t${source:Version}', component['name']],
                            capture_output=True, text=True, check=True)
    name, version = result.stdout.strip().split('\t')
    subprocess.run(['apt-get', 'source', '--download-only', '--only-source', f'{name}={version}'],
                   cwd=target, check=True, timeout=600)
    controls = list(target.glob('*.dsc'))
    if len(controls) != 1:
        raise ValueError(f'Expected exact Debian source control file for {name}={version}')
    text = controls[0].read_text()
    section = re.search(r'^Checksums-Sha256:\n((?: [^\n]+\n)+)', text, re.M)
    if not section:
        raise ValueError('Debian source lacks SHA-256 records')
    records = []
    for line in section.group(1).splitlines():
        sha, size, filename = line.split()
        if Path(filename).name != filename:
            raise ValueError('Unsafe Debian source filename')
        path = target / filename
        if not path.is_file() or path.stat().st_size != int(size) or digest(path) != sha:
            raise ValueError(f'Debian source checksum mismatch: {filename}')
        records.append({'file': filename, 'sha256': sha})
    records.append({'file': controls[0].name, 'sha256': digest(controls[0])})
    return {'package': name, 'version': version, 'files': records}


def build_sources(report, entries, root, output, cache, native=None):
    """Use the same upstream archive bytes as the notice provenance."""
    root, output = Path(root), Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest = {'application': report['application'], 'target': report['target'], 'upstream': [], 'native': []}
    with tempfile.TemporaryDirectory(prefix='source-layout-', dir=root / 'build') as temporary:
        layout = Path(temporary)
        upstream = layout / 'upstream'
        upstream.mkdir()
        urls = {}
        for catalog, records in report['notice_catalogs'].items():
            for record in records:
                if 'source_archive_sha256' in record:
                    url, sha = record['upstream_url'], record['source_archive_sha256']
                    if url in urls and urls[url][1] != sha:
                        raise ValueError('Conflicting upstream source hashes')
                    urls[url] = (catalog, sha)
        for component in report['components']:
            if component['name'].lower() == 'pyinstaller':
                url = f'https://codeload.github.com/pyinstaller/pyinstaller/tar.gz/refs/tags/v{component["version"]}'
                urls[url] = ('pyinstaller', digest(cache.fetch(url)))
        for url, (catalog, sha) in sorted(urls.items()):
            path = cache.fetch(url)
            if digest(path) != sha:
                raise ValueError(f'Upstream source differs from notice provenance: {catalog}')
            # tarfile detects bzip2/xz streams too; preserve original bytes.
            with tarfile.open(path):
                pass
            with path.open('rb') as stream:
                magic = stream.read(6)
            suffix = '.tar.gz' if magic.startswith(b'\x1f\x8b') else '.tar.bz2' if magic.startswith(b'BZ') else '.tar.xz' if magic.startswith(b'\xfd7zXZ') else '.tar'
            name = slug(catalog) + '.source' + suffix
            shutil.copyfile(path, upstream / name)
            manifest['upstream'].append({'component': catalog, 'file': 'upstream/' + name, 'url': url, 'sha256': sha})
        for component in report['components']:
            if component['provider'] not in {'homebrew', 'dpkg'}:
                continue
            target = layout / 'native' / slug(component['id'])
            target.mkdir(parents=True)
            if native:
                record = native(component, target)
            elif component['provider'] == 'homebrew':
                record = homebrew_sources(component, entries, target, cache.directory / 'native')
            else:
                record = debian_sources(component, target)
            manifest['native'].append({'component': component['id'], 'directory': target.relative_to(layout).as_posix(), 'source': record})
        # Git's tracked snapshot excludes local configuration, caches and secrets.
        subprocess.run(['git', 'archive', '--format=tar', '--output', str(layout / 'application.tar'), report['application']['commit']],
                       cwd=root, check=True)
        shutil.copyfile(root / 'packaging' / 'source-build.md', layout / 'BUILD.md')
        shutil.copyfile(root / 'pyproject.toml', layout / 'pyproject.toml')
        (layout / 'manifest.json').write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')
        (layout / 'inventory.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
        with tarfile.open(output, 'w:gz', compresslevel=1) as archive:
            for path in sorted(layout.rglob('*')):
                if path.is_file():
                    archive.add(path, arcname='rigctl-launcher-sources/' + path.relative_to(layout).as_posix())
        output.with_name(output.name + '.sha256').write_text(f'{digest(output)}  {output.name}\n')
    return manifest
