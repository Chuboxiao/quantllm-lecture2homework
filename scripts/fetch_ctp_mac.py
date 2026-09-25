"""Restore the pinned macOS CTP source subset and verify every Git blob."""
import base64
import hashlib
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'raw/repos/vnpy_ctp_mac_6_7_7'
manifest = json.loads((ROOT/'reports/ctp-compat-source.json').read_text())
assert manifest['commit'] == 'fa199f70dac9e242c20e925c17e2241b877e694f'

def digest(data):
    return hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()

for entry in manifest['git_tree']:
    target = DEST/entry['path']
    exists = target.exists() or target.is_symlink()
    if exists:
        data = str(target.readlink()).encode() if target.is_symlink() else target.read_bytes()
    else:
        url = f"https://api.github.com/repos/vnpy/vnpy_ctp/git/blobs/{entry['sha']}"
        request = urllib.request.Request(url, headers={'Accept':'application/vnd.github+json'})
        with urllib.request.urlopen(request, timeout=60) as response:
            data = base64.b64decode(json.load(response)['content'])
    if digest(data) != entry['sha']:
        raise SystemExit(f'Hash mismatch; source left unchanged: {entry["path"]}')
    if not exists:
        target.parent.mkdir(parents=True, exist_ok=True)
        if entry['mode'] == '120000':
            target.symlink_to(data.decode())
        else:
            target.write_bytes(data)
print(f'Verified {len(manifest["git_tree"])} files for {manifest["commit"]}')
