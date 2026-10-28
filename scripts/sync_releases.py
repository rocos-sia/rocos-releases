#!/usr/bin/env python3
"""Mirror complete, verified public ROCOS releases; never replace published assets."""
import argparse
import hashlib
import json
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from semver import Version

ROOT = Path(__file__).resolve().parents[1]
DESTINATION = 'rocos-sia/rocos-releases'
SAFE_NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9._+-]*\Z')


def run(*args):
    return subprocess.check_output(args, text=True, timeout=600).strip()


def api(path):
    return json.loads(run('gh', 'api', path))


def releases(repo):
    pages = json.loads(run('gh', 'api', '--paginate', '--slurp',
                          f'repos/{repo}/releases?per_page=100'))
    return [release for page in pages for release in page]


def candidates(items, channel):
    result = []
    for release in items:
        if release['draft'] or release['prerelease'] != (channel == 'internal'):
            continue
        tag = release['tag_name']
        try:
            version = Version.parse(tag.removeprefix('v'))
        except ValueError:
            continue
        if bool(version.prerelease) != release['prerelease']:
            raise ValueError(f'{tag}: tag and GitHub prerelease flag disagree')
        if not any(a['name'] == 'release.json' for a in release['assets']):
            continue  # Legacy releases have no machine-readable packaging contract.
        result.append((version, release))
    return sorted(result, key=lambda item: item[0], reverse=True)


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def download(repo, release, name, directory):
    if not SAFE_NAME.fullmatch(name):
        raise ValueError(f'Unsafe asset name: {name!r}')
    assets = [a for a in release['assets'] if a['name'] == name]
    if len(assets) != 1 or assets[0]['state'] != 'uploaded':
        raise ValueError(f'{repo}: missing or unfinished asset {name}')
    asset = assets[0]
    if name == 'release.json' and asset['size'] > 1024 * 1024:
        raise ValueError('Oversized release descriptor')
    run('gh', 'release', 'download', release['tag_name'], '--repo', repo,
        '--pattern', name, '--dir', str(directory))
    path = directory / name
    if path.stat().st_size != asset['size']:
        raise ValueError(f'{name}: GitHub size mismatch')
    expected = asset.get('digest')
    if expected and expected != 'sha256:' + digest(path):
        raise ValueError(f'{name}: GitHub digest mismatch')
    return path


def validate_descriptor(data, component, release):
    schema = json.loads((ROOT / 'schemas/source-release.schema.json').read_text())
    Draft202012Validator(schema).validate(data)
    if data['component'] != component or 'v' + data['version'] != release['tag_name']:
        raise ValueError('Descriptor component/version differs from source tag')
    if bool(Version.parse(data['version']).prerelease) != release['prerelease']:
        raise ValueError('Descriptor channel differs from source release')
    names = [a['name'] for a in data['assets']]
    platforms = [(a['os'], a['arch'], a['format']) for a in data['assets']]
    if len(set(names)) != len(names) or len(set(platforms)) != len(platforms):
        raise ValueError('Duplicate asset or platform')
    for name in names:
        if not SAFE_NAME.fullmatch(name):
            raise ValueError('Unsafe package name')


def verify_deb(path, asset, data):
    if path.stat().st_size != asset['size_bytes'] or digest(path) != asset['sha256']:
        raise ValueError(f'{path.name}: package size/SHA256 mismatch')
    fields = run('dpkg-deb', '-f', str(path), 'Package', 'Version', 'Architecture')
    actual = dict(line.split(': ', 1) for line in fields.splitlines())
    expected_version = data['version'].replace('-', '~', 1)
    if actual != {'Package': 'rocos-' + data['component'],
                  'Version': expected_version, 'Architecture': asset['arch']}:
        raise ValueError(f'{path.name}: unexpected Debian metadata: {actual}')


def mirror(repo, component, source, dry_run=False):
    with tempfile.TemporaryDirectory(prefix='rocos-release-') as tmp:
        directory = Path(tmp)
        descriptor = download(repo, source, 'release.json', directory)
        data = json.loads(descriptor.read_text())
        validate_descriptor(data, component, source)
        for asset in data['assets']:
            path = download(repo, source, asset['name'], directory)
            verify_deb(path, asset, data)
        sums = directory / 'SHA256SUMS'
        sums.write_text(''.join(f'{digest(p)}  {p.name}\n'
                               for p in sorted(directory.iterdir()) if p != sums))
        if dry_run:
            print(f'Verified {repo}@{source["tag_name"]}; dry run, no writes')
            return None
        tag = f'{component}-{source["tag_name"]}'
        existing = next((r for r in releases(DESTINATION) if r['tag_name'] == tag), None)
        notes = directory / 'notes.md'
        notes.write_text(f'Source: {source["html_url"]}\n\n{source.get("body") or ""}')
        files = [str(directory / a['name']) for a in data['assets']]
        files += [str(descriptor), str(sums)]
        if existing is None:
            args = ['gh', 'release', 'create', tag, *files, '--repo', DESTINATION,
                    '--target', run('git', '-C', str(ROOT), 'rev-parse', 'HEAD'),
                    '--draft', '--title', f'{component} {data["version"]}',
                    '--notes-file', str(notes)]
            if source['prerelease']:
                args.append('--prerelease')
            run(*args)
        elif existing['draft']:
            run('gh', 'release', 'upload', tag, *files, '--repo', DESTINATION, '--clobber')
        release_id = next(r['id'] for r in releases(DESTINATION) if r['tag_name'] == tag)
        remote = api(f'repos/{DESTINATION}/releases/{release_id}')
        if remote['prerelease'] != source['prerelease']:
            raise ValueError(f'{tag}: destination channel conflict')
        verify_dir = directory / 'verify'
        verify_dir.mkdir()
        for file in files:
            local = Path(file)
            downloaded = download(DESTINATION, remote, local.name, verify_dir)
            if digest(downloaded) != digest(local):
                raise ValueError(f'{tag}: published asset conflict; will not overwrite')
        if remote['draft']:
            run('gh', 'release', 'edit', tag, '--repo', DESTINATION,
                '--draft=false', '--latest=false')
            remote = api(f'repos/{DESTINATION}/releases/{release_id}')
        urls = {a['name']: a['browser_download_url'] for a in remote['assets']}
        return {
            'version': data['version'], 'prerelease': source['prerelease'],
            'source_repository': repo, 'tag': source['tag_name'],
            'published_at': source['published_at'], 'release_url': remote['html_url'],
            'notes': source.get('body') or '', 'compatibility': data['compatibility'],
            'assets': [{**{k: a[k] for k in ('os', 'arch', 'format', 'size_bytes', 'sha256')},
                        'url': urls[a['name']], 'signature_url': None} for a in data['assets']],
        }


def sync(dry_run=False):
    sources = json.loads((ROOT / 'sources.json').read_text())
    schema = json.loads((ROOT / 'schemas/manifest.schema.json').read_text())
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    channels = {name: json.loads((ROOT / f'channels/{name}.json').read_text())
                for name in ('stable', 'internal')}
    for document in channels.values():
        validator.validate(document)
    changed = set()
    for component, repo in sources.items():
        if repo is None:
            print(f'{component}: source not configured; unchanged')
            continue
        available = releases(repo)
        for channel, document in channels.items():
            options = candidates(available, channel)
            if not options:
                print(f'{component}/{channel}: no packaged release')
                continue
            version, source = options[0]
            current = document['components'][component]
            if current and version <= Version.parse(current['version']):
                print(f'{component}/{channel}: unchanged ({current["version"]})')
                continue
            result = mirror(repo, component, source, dry_run)
            if result:
                document['components'][component] = result
                document['updated_at'] = datetime.now(timezone.utc).isoformat()
                validator.validate(document)
                changed.add(channel)
    # Only publish manifests once every selected component has passed verification.
    for channel in changed:
        path = ROOT / f'channels/{channel}.json'
        temporary = path.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(channels[channel], indent=2, ensure_ascii=False) + '\n')
        temporary.replace(path)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true')
    sync(parser.parse_args().dry_run)
