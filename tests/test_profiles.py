from dataclasses import asdict
import json
from pathlib import Path
import pytest
from rigctl_launcher.profiles import Profile, Settings, Store


def test_fresh_install_has_no_profiles_or_personal_defaults(tmp_path):
    store = Store(tmp_path)
    assert store.load_profiles() == []
    assert not store.errors
    settings = store.load_settings()
    assert settings.port_mode == 'profile'
    assert settings.slots == [4532, 4534, 4536]
    assert not settings.setup_seen
    assert store.directory.is_dir()


def test_readable_roundtrip_and_no_reseed(tmp_path):
    store = Store(tmp_path)
    profile = Profile('new', 'New', 2057, match={'vid': 123, 'serial_number': 'ABC'}, arguments=['-C', 'rts_state=OFF'])
    store.save_profile(profile)
    assert profile in store.load_profiles()
    assert '\n  "name": "New"' in (tmp_path / 'profiles/new.json').read_text()
    store.save_settings(Settings(slots=[5000, 5002]))
    assert Store(tmp_path).load_settings().slots == [5000, 5002]
    for path in (tmp_path / 'profiles').glob('*.json'):
        path.unlink()
    assert Store(tmp_path).load_profiles() == []


def test_bad_profile_reported_not_silently_replaced(tmp_path):
    store = Store(tmp_path)
    (store.directory / 'bad.json').write_text('{broken')
    assert store.load_profiles() == []
    assert 'bad.json' in store.errors[0]


@pytest.mark.parametrize('arg', ['-t', '-t9000', '--port=9000', '-T0.0.0.0', '--listen-addr', '-r/dev/other', '--rig-file', '-b', '--bind-all', '-vv', '-m1', '-p', '--ptt-file=/dev/other', '--'])
def test_managed_arguments_cannot_be_overridden(arg):
    with pytest.raises(ValueError):
        Profile('a', 'Radio', 1, arguments=[arg]).validate()


def test_distinct_usb_interfaces_and_port_move_identity():
    from rigctl_launcher.devices import Device, canonical_path
    d = Device('/dev/fake', vid=1, pid=2, serial_number='ABC', interface='CAT', location='1:1')
    assert d.identity() == {'vid': 1, 'pid': 2, 'serial_number': 'ABC', 'interface': 'CAT', 'path': canonical_path('/dev/fake')}
    assert Device('/dev/fake', vid=1, pid=2, location='1:1').identity()['location'] == '1:1'


@pytest.mark.parametrize('arguments', [['--por=5000'], ['--listen-a=0.0.0.0'], ['-C', 'rig_pathname=/dev/other'], ['--set-conf=serial_speed=9600']])
def test_managed_config_and_abbreviated_options(arguments):
    with pytest.raises(ValueError):
        Profile('a', 'Radio', 1, arguments=arguments).validate()


def test_additional_config_compact_form():
    Profile('a', 'Radio', 1, arguments=['-Crts_state=OFF', '-W1.5']).validate()


@pytest.mark.parametrize('changes', [{'id': None}, {'name': None}, {'manual_device': None}, {'executable': None}])
def test_invalid_field_types_are_reported(changes):
    from dataclasses import replace
    with pytest.raises(ValueError):
        replace(Profile('a', 'Radio', 1), **changes).validate()


def test_upgrade_preserves_saved_profiles_and_settings(tmp_path, monkeypatch):
    from rigctl_launcher import profiles as module
    legacy = tmp_path / 'rigctld-manager'
    destination = tmp_path / 'rigctl-launcher'
    old_store = Store(legacy)
    saved = Profile('my-radio', 'My radio', 2057, baud=115200,
                    match={'serial_number': 'remembered'}, manual_device='/dev/my-radio',
                    preferred_port=5010, executable='/my/rigctld')
    old_store.save_profile(saved)
    old_store.save_settings(Settings(executable='/custom/rigctld', port_mode='slots', slots=[5010, 5012]))
    # Preserve even an intentionally removed seed profile and unrelated saved data.
    old_store.save_profile(Profile('removed', 'Removed example', 1))
    (legacy / 'profiles/removed.json').unlink()
    (legacy / 'notes.txt').write_text('Keep this too')
    before = {str(p.relative_to(legacy)): p.read_bytes() for p in legacy.rglob('*') if p.is_file()}
    monkeypatch.setattr(module, 'config_dir', lambda name='rigctl-launcher': tmp_path / name)
    migrated = Store()
    assert migrated.root == destination
    assert saved in migrated.load_profiles()
    assert not (destination / 'profiles/removed.json').exists()
    assert migrated.load_settings() == old_store.load_settings()
    after = {str(p.relative_to(destination)): p.read_bytes() for p in destination.rglob('*') if p.is_file()}
    assert before == after
    assert before == {str(p.relative_to(legacy)): p.read_bytes() for p in legacy.rglob('*') if p.is_file()}
    migrated.save_settings(Settings(executable='/new/rigctld', slots=[6000]))
    assert Store().load_settings().executable == '/new/rigctld'
    assert old_store.load_settings().executable == '/custom/rigctld'


def test_existing_named_config_takes_precedence(tmp_path, monkeypatch):
    from rigctl_launcher import profiles as module
    legacy = Store(tmp_path / 'rigctld-manager')
    legacy.save_settings(Settings(executable='/old/rigctld'))
    current = Store(tmp_path / 'rigctl-launcher')
    current.save_settings(Settings(executable='/new/rigctld'))
    monkeypatch.setattr(module, 'config_dir', lambda name='rigctl-launcher': tmp_path / name)
    assert Store().load_settings().executable == '/new/rigctld'


def test_failed_migration_leaves_no_partial_destination(tmp_path, monkeypatch):
    from rigctl_launcher import profiles as module
    legacy = tmp_path / 'rigctld-manager'
    destination = tmp_path / 'rigctl-launcher'
    Store(legacy).save_profile(Profile('saved', 'Saved example', 1))
    original = module.shutil.copytree
    def fail_copy(source, target):
        target.mkdir()
        (target / 'partial.json').write_text('incomplete')
        raise OSError('Simulated interrupted copy')
    monkeypatch.setattr(module.shutil, 'copytree', fail_copy)
    with pytest.raises(OSError, match='interrupted copy'):
        module.migrate_config(destination, legacy)
    assert not destination.exists()
    assert not list(tmp_path.glob('rigctl-launcher-migrate-*'))
    monkeypatch.setattr(module.shutil, 'copytree', original)
    module.migrate_config(destination, legacy)
    assert (destination / 'profiles/saved.json').exists()


@pytest.mark.parametrize('platform', ['darwin', 'win32', 'linux'])
def test_named_config_directory_on_each_platform(tmp_path, monkeypatch, platform):
    from rigctl_launcher import profiles as module
    monkeypatch.setattr(module.sys, 'platform', platform)
    monkeypatch.setattr(module.Path, 'home', lambda: tmp_path)
    monkeypatch.setenv('APPDATA', str(tmp_path / 'appdata'))
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'xdg'))
    expected = {'darwin': tmp_path / 'Library/Application Support', 'win32': tmp_path / 'appdata', 'linux': tmp_path / 'xdg'}[platform]
    assert module.config_dir() == expected / 'rigctl-launcher'
    assert module.config_dir('rigctld-manager') == expected / 'rigctld-manager'
