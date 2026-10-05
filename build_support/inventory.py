"""Record collected modules and native files without disclosing build paths."""
import ast
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import tomllib


KINDS = {'PYMODULE', 'PYSOURCE', 'BINARY', 'EXTENSION', 'DATA', 'EXECUTABLE'}


def collected_entries(work):
    entries = set()
    paths = list(Path(work).glob('*.toc'))
    if not paths:
        raise ValueError('No PyInstaller collection records found')
    for path in paths:
        # Windows EXE records also contain VSVersionInfo(...) expressions.
        # Read only literal tagged triples; never evaluate surrounding objects.
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, (ast.Tuple, ast.List)) and len(node.elts) == 3:
                if all(isinstance(item, ast.Constant) and isinstance(item.value, str) for item in node.elts):
                    value = tuple(item.value for item in node.elts)
                    if value[2] in KINDS:
                        entries.add(value)
    return sorted(entries)


def distribution_files(distributions=None):
    owners, packages = {}, {}
    for dist in distributions if distributions is not None else metadata.distributions():
        name = dist.metadata['Name']
        key = re.sub(r'[-_.]+', '-', name).lower()
        packages[key] = {'name': name, 'version': dist.version,
                         'license_expression': dist.metadata.get('License-Expression'),
                         'license_metadata': dist.metadata.get('License')}
        for file in dist.files or []:
            owners.setdefault(Path(dist.locate_file(file)).resolve(), key)
    return owners, packages


def native_provider(path):
    """Identify native providers from local package-manager metadata, never probes."""
    parts = path.resolve().parts
    if 'Cellar' in parts:
        index = parts.index('Cellar')
        if len(parts) > index + 2:
            return {'name': parts[index + 1], 'version': parts[index + 2], 'provider': 'homebrew'}
    if sys.platform.startswith('linux'):
        result = subprocess.run(['dpkg-query', '-S', str(path)], capture_output=True, text=True, timeout=5, check=False)
        if result.returncode and str(path).startswith('/usr/lib/'):
            result = subprocess.run(['dpkg-query', '-S', str(path)[4:]], capture_output=True, text=True, timeout=5, check=False)
        if result.returncode == 0:
            package = result.stdout.split(': ', 1)[0].splitlines()[0]
            version = subprocess.run(['dpkg-query', '-W', '-f=${Version}', package], capture_output=True, text=True, timeout=5, check=False)
            if version.returncode == 0:
                return {'name': package, 'version': version.stdout.strip(), 'provider': 'dpkg'}
    return None


def file_version(path):
    """Read Windows fixed version resources without executing the DLL."""
    if os.name != 'nt':
        return None
    import ctypes
    from ctypes import wintypes
    api = ctypes.WinDLL('version', use_last_error=True)
    api.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
    api.GetFileVersionInfoSizeW.restype = wintypes.DWORD
    api.GetFileVersionInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
    api.VerQueryValueW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.UINT)]
    size = api.GetFileVersionInfoSizeW(str(path), None)
    if not size:
        return None
    data = ctypes.create_string_buffer(size)
    if not api.GetFileVersionInfoW(str(path), 0, size, data):
        return None
    pointer, length = ctypes.c_void_p(), wintypes.UINT()
    if not api.VerQueryValueW(data, '\\', ctypes.byref(pointer), ctypes.byref(length)) or length.value < 52:
        return None
    words = ctypes.cast(pointer, ctypes.POINTER(wintypes.DWORD))
    ms, ls = words[2], words[3]
    return f'{ms >> 16}.{ms & 65535}.{ls >> 16}.{ls & 65535}'


def describe_sources(entries, owners, packages, root, python_root=None, provider=native_provider):
    python_root = Path(python_root or sys.base_prefix).resolve()
    root = Path(root).resolve()
    components, files = {}, []
    cache = {}
    for destination, source, kind in entries:
        path = Path(source)
        if not path.is_file():
            continue
        resolved = path.resolve()
        name = resolved.name.lower()
        if name == 'base_library.zip':
            component = {'name': 'cpython', 'version': platform.python_version(), 'provider': 'python-runtime'}
        elif resolved.is_relative_to(root) and '.venv' not in resolved.relative_to(root).parts:
            component = {'name': 'rigctl-launcher', 'version': project_version(root), 'provider': 'project'}
        elif sys.platform == 'win32' and name.startswith(('libcrypto', 'libssl', 'libffi')) and name.endswith('.dll'):
            component = {'name': 'libffi' if name.startswith('libffi') else 'openssl', 'version': file_version(path), 'provider': 'windows-native-library'}
        elif re.match(r'(vcruntime|msvcp|concrt|ucrtbase|api-ms-win-).*\.dll$', name):
            component = {'name': 'microsoft-c-runtime', 'version': file_version(path), 'provider': 'windows-version-resource'}
        elif resolved in owners:
            key = owners[resolved]
            component = {**packages[key], 'provider': 'python-distribution'}
        elif resolved.is_relative_to(python_root):
            component = {'name': 'cpython', 'version': platform.python_version(), 'provider': 'python-runtime'}
        else:
            if resolved not in cache:
                try:
                    cache[resolved] = provider(resolved)
                except (OSError, subprocess.SubprocessError):
                    cache[resolved] = None
            component = cache[resolved] or {'name': name, 'version': None, 'provider': 'unresolved-native'}
        identifier = f'{component["provider"]}:{component["name"]}:{component["version"] or "unknown"}'
        components[identifier] = {'id': identifier, **component}
        files.append({'name': destination.replace('\\', '/'), 'kind': kind, 'component': identifier})
    return sorted(components.values(), key=lambda x: x['id']), files


def project_version(root):
    return tomllib.loads((Path(root) / 'pyproject.toml').read_text())['project']['version']


def artifact_files(target):
    result = []
    for path in sorted(Path(target).rglob('*')):
        relative = path.relative_to(target).as_posix()
        if path.is_symlink():
            link = os.readlink(path)
            if Path(link).is_absolute() or not path.resolve().is_relative_to(Path(target).resolve()):
                raise ValueError(f'Package symlink leaves the application: {relative}')
            result.append({'path': relative, 'symlink': link})
        elif path.is_file():
            with path.open('rb') as stream:
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            result.append({'path': relative, 'size': path.stat().st_size, 'sha256': digest})
    return result


def write_inventory(target, work, root, destination):
    from PySide6.QtCore import qVersion
    owners, packages = distribution_files()
    components, files = describe_sources(collected_entries(work), owners, packages, root)
    commit = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=root, capture_output=True, text=True, check=True).stdout.strip()
    report = {'schema_version': 1, 'application': {'name': 'rigctl-launcher', 'version': project_version(root), 'commit': commit},
              'target': {'os': platform.system().lower(), 'architecture': platform.machine().lower()},
              'runtime': {'python': platform.python_version(), 'qt': qVersion()},
              'build_tools': [packages[key] for key in ('pyinstaller', 'pyinstaller-hooks-contrib') if key in packages],
              'components': components, 'collected_files': files, 'artifact_files': artifact_files(target),
              'scope': 'Collected modules and native providers. Embedded third-party code within those libraries requires upstream attribution records; this is not a complete SPDX SBOM.'}
    Path(destination).write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    return report
