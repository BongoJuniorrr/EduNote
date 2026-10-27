"""Verify and stream-load bundled Docker images. No network or build is required."""
import hashlib
import json
from pathlib import Path
import subprocess
root=Path(__file__).resolve().parents[1]
manifest=root/'runtime'/'manifest.json'
if not manifest.exists():raise SystemExit('Download and extract all runtime ZIP parts from the GitHub release, or build from source as described in README.md.')
info=json.loads(manifest.read_text())
paths=[]
for part in info['parts']:
    p=root/'runtime'/part['name']
    if not p.is_file():raise SystemExit('Missing runtime part: '+part['name'])
    h=hashlib.sha256()
    with p.open('rb') as stream:
        for block in iter(lambda:stream.read(8*1024*1024),b''):h.update(block)
    if h.hexdigest()!=part['sha256']:raise SystemExit('Checksum mismatch: '+part['name'])
    paths.append(p)
# Docker load accepts a gzip-compressed stream even when divided into files.
process=subprocess.Popen(['docker','load'],stdin=subprocess.PIPE)
try:
    for path in paths:
        with path.open('rb') as stream:
            for block in iter(lambda:stream.read(8*1024*1024),b''):process.stdin.write(block)
    process.stdin.close()
    if process.wait():raise SystemExit('docker load failed')
except BaseException:
    process.terminate();process.wait();raise
print('Release images verified and loaded.')
