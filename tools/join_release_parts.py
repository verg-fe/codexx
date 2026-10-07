"""Join numbered release assets and verify the original ZIP SHA256."""
import argparse
import hashlib
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description='Join downloaded codexx Release parts with SHA256 verification.')
    parser.add_argument('--directory', type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    folder = args.directory.resolve()
    manifest = json.loads((folder / 'release-assets-manifest.json').read_text(encoding='utf-8'))
    for name, original in manifest['archives'].items():
        if Path(name).name != name:
            raise ValueError('Archive names must be simple file names')
        parts = sorted((row for row in manifest['assets'] if row['archive'] == name), key=lambda row: row['name'])
        for row in parts:
            if Path(row['name']).name != row['name']:
                raise ValueError('Part names must be simple file names')
            part = folder / row['name']
            with part.open('rb') as stream:
                value = hashlib.file_digest(stream, 'sha256').hexdigest()
            if value != row['sha256'] or part.stat().st_size != row['bytes']:
                raise RuntimeError('Part verification failed: ' + part.name)
        output = folder / name
        if len(parts) == 1 and parts[0]['name'] == name:
            print('Verified: ' + name)
            continue
        if output.exists():
            with output.open('rb') as stream:
                actual = hashlib.file_digest(stream, 'sha256').hexdigest()
            if actual == original['sha256']:
                print('Already joined: ' + name)
                continue
            raise FileExistsError('A different output already exists: ' + str(output))
        temporary = output.with_name(output.name + '.joining')
        if temporary.exists():
            raise FileExistsError(temporary)
        combined = hashlib.sha256()
        with temporary.open('xb') as target:
            for row in parts:
                with (folder / row['name']).open('rb') as source:
                    while chunk := source.read(4 * 1024 * 1024):
                        combined.update(chunk)
                        target.write(chunk)
        if combined.hexdigest() != original['sha256'] or temporary.stat().st_size != original['bytes']:
            raise RuntimeError('Joined archive verification failed: ' + name)
        temporary.rename(output)
        print('Joined and verified: ' + name)


if __name__ == '__main__':
    main()
