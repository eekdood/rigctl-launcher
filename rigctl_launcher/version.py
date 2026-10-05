"""Read application version without copying local installation metadata into builds."""
from importlib import metadata
import json
from pathlib import Path
import sys
import tomllib


def application_version():
    if getattr(sys, 'frozen', False):
        path = Path(sys._MEIPASS) / 'application-metadata.json'
        version = json.loads(path.read_text())['version']
        if not isinstance(version, str) or not version:
            raise ValueError('Invalid packaged application version')
        return version
    project = Path(__file__).resolve().parents[1] / 'pyproject.toml'
    if project.is_file():
        return tomllib.loads(project.read_text())['project']['version']
    return metadata.version('rigctl-launcher')
