"""Stage application-only downloads from native build output."""
import json
from pathlib import Path
import shutil
import tempfile
from .release_assets import verify_checksum


def stage_downloads(inputs, destination):
    inputs, destination = Path(inputs).resolve(), Path(destination).resolve()
    if inputs == destination or inputs.is_relative_to(destination) or destination.is_relative_to(inputs):
        raise ValueError('Download input and output directories must be separate')
    applications = []
    for inventory in sorted(inputs.glob('*.inventory.json')):
        report = json.loads(inventory.read_text())
        label = inventory.name.removesuffix('.inventory.json')
        extension = '.tar.gz' if report['target']['os'] == 'linux' else '.zip'
        archive = inputs / (label + extension)
        verify_checksum(archive)
        applications.extend((archive, archive.with_name(archive.name + '.sha256')))
    if not applications:
        raise ValueError('No application downloads found')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='app-downloads-', dir=destination.parent) as temporary:
        staging = Path(temporary)
        for path in applications:
            shutil.copyfile(path, staging / path.name)
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(staging, destination)
    return sorted(path.name for path in destination.iterdir())
