import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from jsonschema import ValidationError, Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('sync', ROOT / 'scripts/sync_releases.py')
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)


def release(version, draft=False, packaged=True):
    return {'tag_name': 'v' + version, 'draft': draft, 'prerelease': '-' in version,
            'assets': [{'name': 'release.json'}] if packaged else []}


def descriptor():
    return {'schema_version': 1, 'component': 'app', 'version': '3.2.0-rc.1',
            'compatibility': {'api_version': '3.0.0', 'shm_abi_version': 2},
            'assets': [{'name': 'rocos-app_3.2.0-rc.1_amd64.deb', 'os': 'linux',
                        'arch': 'amd64', 'format': 'deb', 'size_bytes': 3,
                        'sha256': 'a' * 64}]}


class SyncTest(unittest.TestCase):
    def test_source_pat_is_only_used_for_source_commands(self):
        environment = {'GH_TOKEN': 'destination-test-token',
                       'SOURCE_GH_TOKEN': 'source-test-token'}
        with patch.dict(sync.os.environ, environment, clear=True), \
                patch.object(sync.subprocess, 'check_output', return_value='[]') as command:
            sync.releases('private/app', source=True)
            self.assertEqual(command.call_args.kwargs['env']['GH_TOKEN'],
                             'source-test-token')
            self.assertNotIn('SOURCE_GH_TOKEN', command.call_args.kwargs['env'])
            self.assertNotIn('source-test-token', str(command.call_args.args))
            sync.releases(sync.DESTINATION)
            self.assertEqual(command.call_args.kwargs['env']['GH_TOKEN'],
                             'destination-test-token')
            self.assertNotIn('SOURCE_GH_TOKEN', command.call_args.kwargs['env'])
            self.assertEqual(sync.os.environ['GH_TOKEN'], 'destination-test-token')

    def test_source_without_pat_keeps_default_authentication(self):
        for environment in ({}, {'GH_TOKEN': 'default-test-token'},
                            {'GH_TOKEN': 'default-test-token', 'SOURCE_GH_TOKEN': ''}):
            with self.subTest(environment=environment), \
                    patch.dict(sync.os.environ, environment, clear=True), \
                    patch.object(sync.subprocess, 'check_output', return_value='[]') as command:
                sync.releases('public/app', source=True)
                self.assertEqual(command.call_args.kwargs['env'].get('GH_TOKEN'),
                                 environment.get('GH_TOKEN'))
                self.assertNotIn('SOURCE_GH_TOKEN', command.call_args.kwargs['env'])

    def test_download_uses_selected_credentials(self):
        item = release('3.2.0')
        item['assets'] = [{'name': 'release.json', 'size': 2, 'state': 'uploaded'}]
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / 'release.json').write_bytes(b'{}')
            for source in (True, False):
                with patch.object(sync, 'run') as command:
                    sync.download('owner/repo', item, 'release.json', directory,
                                  source=source)
                    self.assertEqual(command.call_args.kwargs, {'source': source})

    def test_semver_numeric_rc_and_channel_separation(self):
        items = [release(v) for v in ('3.2.0-rc.2', '3.2.0-rc.10', '3.2.0', '3.1.99')]
        self.assertEqual(str(sync.candidates(items, 'internal')[0][0]), '3.2.0-rc.10')
        self.assertEqual(str(sync.candidates(items, 'stable')[0][0]), '3.2.0')

    def test_drafts_unpackaged_and_invalid_tags_are_ignored(self):
        self.assertEqual(sync.candidates([release('9.0.0', draft=True),
                                         release('8.0.0', packaged=False),
                                         release('latest')], 'stable'), [])

    def test_mislabeled_release_is_rejected(self):
        item = release('3.2.0-rc.1')
        item['prerelease'] = False
        with self.assertRaises(ValueError):
            sync.candidates([item], 'stable')

    def test_descriptor_matches_source(self):
        sync.validate_descriptor(descriptor(), 'app', release('3.2.0-rc.1'))
        with self.assertRaises(ValueError):
            sync.validate_descriptor(descriptor(), 'viz', release('3.2.0-rc.1'))
        with self.assertRaises(ValueError):
            sync.validate_descriptor(descriptor(), 'app', release('3.2.0-rc.2'))

    def test_traversal_bad_checksum_duplicate_platform_rejected(self):
        for field, value in [('name', '../x.deb'), ('name', 'app_3.2.0~rc.1_amd64.deb'),
                             ('sha256', 'bad'), ('size_bytes', 0)]:
            data = descriptor()
            data['assets'][0][field] = value
            with self.assertRaises(ValidationError):
                sync.validate_descriptor(data, 'app', release('3.2.0-rc.1'))
        data = descriptor()
        data['assets'].append(copy.deepcopy(data['assets'][0]))
        data['assets'][1]['name'] = 'different.deb'
        with self.assertRaises(ValueError):
            sync.validate_descriptor(data, 'app', release('3.2.0-rc.1'))

    def test_deb_contents_and_hash_not_just_filename(self):
        data = descriptor()
        asset = data['assets'][0]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / asset['name']
            path.write_bytes(b'deb')
            asset['sha256'] = sync.digest(path)
            with patch.object(sync, 'run', return_value='Package: rocos-app\nVersion: 3.2.0~rc.1\nArchitecture: amd64'):
                sync.verify_deb(path, asset, data)
            with patch.object(sync, 'run', return_value='Package: unexpected\nVersion: 3.2.0~rc.1\nArchitecture: amd64'):
                with self.assertRaises(ValueError):
                    sync.verify_deb(path, asset, data)
            path.write_bytes(b'bad')
            with self.assertRaises(ValueError):
                sync.verify_deb(path, asset, data)

    def test_channels_remain_untouched_if_any_mirror_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for folder in ('channels', 'schemas'):
                (root / folder).mkdir()
                for path in (ROOT / folder).glob('*.json'):
                    (root / folder / path.name).write_bytes(path.read_bytes())
            (root / 'sources.json').write_text(json.dumps({'app': 'a/app', 'viz': 'a/viz'}))
            before = (root / 'channels/internal.json').read_bytes()
            with patch.object(sync, 'ROOT', root), patch.object(sync, 'releases', return_value=[release('3.2.0-rc.1')]), patch.object(sync, 'mirror', side_effect=RuntimeError('upload failed')):
                with self.assertRaises(RuntimeError):
                    sync.sync()
            self.assertEqual((root / 'channels/internal.json').read_bytes(), before)

    def test_checked_in_channels_validate(self):
        validator = Draft202012Validator(json.loads((ROOT / 'schemas/manifest.schema.json').read_text()), format_checker=FormatChecker())
        for path in (ROOT / 'channels').glob('*.json'):
            validator.validate(json.loads(path.read_text()))


if __name__ == '__main__':
    unittest.main()
