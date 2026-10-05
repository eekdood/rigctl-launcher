"""Assemble public downloads, preserving platform-specific source provenance."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import tarfile
import tempfile
import zipfile
from .sources import digest
from .versioning import archive_label


def verify_checksum(path):
    words = path.with_name(path.name + '.sha256').read_text().split()
    if len(words) != 2 or words[1] != path.name or digest(path) != words[0]:
        raise ValueError(f'Checksum mismatch: {path.name}')


def source_members(archive):
    members = {}
    for member in archive.getmembers():
        path = PurePosixPath(member.name)
        if path.is_absolute() or '..' in path.parts or not path.parts or path.parts[0] != 'rigctl-launcher-sources':
            raise ValueError('Unsafe source archive path')
        if member.isdir():
            continue
        if not member.isfile():
            raise ValueError('Source archive contains a link or special file')
        relative = path.relative_to('rigctl-launcher-sources').as_posix()
        if relative in members:
            raise ValueError('Duplicate source archive path')
        members[relative] = member
    return members


def read_json(archive, members, name):
    return json.load(archive.extractfile(members[name]))


def combine_sources(reports, destination):
    shared = {}
    index = []
    prefix = 'rigctl-launcher-sources/'
    with zipfile.ZipFile(destination, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=1) as output:
        for label, inventory, path in reports:
            with tarfile.open(path) as archive:
                members = source_members(archive)
                manifest = read_json(archive, members, 'manifest.json')
                if read_json(archive, members, 'inventory.json') != inventory:
                    raise ValueError(f'Source inventory differs from package inventory: {label}')
                if manifest['application'] != inventory['application'] or manifest['target'] != inventory['target'] or manifest.get('build') != inventory.get('build'):
                    raise ValueError(f'Source provenance differs from package: {label}')
                platform_root = 'platforms/' + label
                platform_files = {'manifest.json'}
                def share(name, expected=None):
                    member = members[name]
                    hasher = hashlib.sha256()
                    with archive.extractfile(member) as stream:
                        while chunk := stream.read(1024 * 1024):
                            hasher.update(chunk)
                    sha = hasher.hexdigest()
                    if expected is not None and sha != expected:
                        raise ValueError(f'Source member checksum mismatch: {name}')
                    if sha not in shared:
                        shared[sha] = 'shared/' + sha + '-' + PurePosixPath(name).name
                        with archive.extractfile(member) as source, output.open(prefix + shared[sha], 'w', force_zip64=True) as target:
                            shutil.copyfileobj(source, target)
                    platform_files.add(name)
                    return shared[sha]
                manifest['application_source'] = share('application.tar')
                manifest['paths_relative_to'] = 'rigctl-launcher-sources/'
                for record in manifest['upstream']:
                    record['file'] = share(record['file'], record['sha256'])
                for record in manifest['native']:
                    record['directory'] = platform_root + '/' + record['directory']
                # Keep distro source files beside their .dsc and recipes, with
                # original names so normal provider build tools still work.
                for name, member in sorted(members.items()):
                    if name in platform_files:
                        continue
                    with archive.extractfile(member) as source, output.open(prefix + platform_root + '/' + name, 'w', force_zip64=True) as target:
                        shutil.copyfileobj(source, target)
                output.writestr(prefix + platform_root + '/manifest.json', json.dumps(manifest, indent=2, sort_keys=True) + '\n')
                index.append({'platform': label, 'manifest': platform_root + '/manifest.json',
                              'inventory': platform_root + '/inventory.json', 'build_instructions': platform_root + '/BUILD.md'})
        output.writestr(prefix + 'index.json', json.dumps(index, indent=2) + '\n')
        output.writestr(prefix + 'README.txt',
            'RigCtl-Launcher application and dependency sources\n\n'
            'Select your platform under platforms/. Its manifest identifies the matching\n'
            'application source, upstream archives, provider patches and build recipes.\n'
            'Manifest paths are relative to this rigctl-launcher-sources directory.\n'
            'Identical archives are stored once under shared/. Extract the application\n'
            'archive identified by application_source, then follow the platform BUILD.md.\n'
            'The platform inventory records the matching binary download and versions.\n')


def prepare_release(inputs, destination, version, expected_systems=('darwin', 'windows', 'linux'), *, identity=None):
    inputs, destination = Path(inputs).resolve(), Path(destination).resolve()
    if inputs == destination or inputs.is_relative_to(destination) or destination.is_relative_to(inputs):
        raise ValueError('Release input and output directories must be separate')
    identity = identity or {'kind': 'release', 'name': version}
    reports, applications = [], []
    systems, commits, labels = set(), set(), set()
    for path in sorted(inputs.glob('*.inventory.json')):
        inventory = json.loads(path.read_text())
        if inventory['application']['version'] != version:
            raise ValueError('Package version differs from release version')
        if inventory.get('build', {'kind': 'release', 'name': version}) != identity:
            raise ValueError('Build identity differs across downloads or from requested build')
        target = inventory['target']
        label = archive_label({'version': version}, target['os'], target['architecture'], build_name=identity['name'])
        if path.name != label + '.inventory.json' or label in labels:
            raise ValueError('Duplicate or unexpected package inventory name')
        labels.add(label)
        systems.add(target['os'])
        commits.add(inventory['application']['commit'])
        source = inputs / (label + '_sources.tar.gz')
        application = inputs / (label + ('.tar.gz' if target['os'] == 'linux' else '.zip'))
        verify_checksum(source)
        verify_checksum(application)
        reports.append((label, inventory, source))
        applications.append(application)
    if systems != set(expected_systems) or len(commits) != 1:
        raise ValueError('Release requires matching builds from all expected platforms and one commit')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='release-assets-', dir=destination.parent) as temporary:
        staging = Path(temporary)
        for application in applications:
            shutil.copyfile(application, staging / application.name)
        combine_sources(reports, staging / f'rigctl-launcher_{identity["name"]}_sources.zip')
        files = sorted(staging.iterdir())
        (staging / 'checksums.txt').write_text(''.join(f'{digest(path)}  {path.name}\n' for path in files))
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(staging, destination)
    return sorted(path.name for path in destination.iterdir())
