from pathlib import Path
import pytest
from rigctl_launcher.executable import locate_executable, require_executable


def test_executable_resolution_without_running_it(fake_executable):
    assert locate_executable(fake_executable) == fake_executable
    assert require_executable(fake_executable) == fake_executable


def test_missing_executable_explains_separate_hamlib_install(tmp_path):
    missing = str(tmp_path / 'missing-rigctld')
    assert locate_executable(missing) is None
    with pytest.raises(ValueError, match='installed separately'):
        require_executable(missing)


def test_directory_is_not_an_executable(tmp_path):
    assert locate_executable(str(tmp_path)) is None


def test_empty_selection():
    assert locate_executable('') is None


def test_lookup_by_name(monkeypatch, fake_executable):
    monkeypatch.setenv('PATH', str(Path(fake_executable).parent))
    assert locate_executable(Path(fake_executable).name) == fake_executable
