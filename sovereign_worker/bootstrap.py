"""Railway volume-ownership bootstrap. Only root runs this file, then drops UID.

No shell, credentials, or remote requests. Changes ownership ONLY inside /data/sovereign.
"""
import json
import os
from pathlib import Path
import stat
import sys

UID = GID = 10001
root = Path('/data')
state = root / 'sovereign'


def bootstrap():
    if os.geteuid() != 0:
        raise RuntimeError('bootstrap requires initial root only for volume ownership')
    if not root.is_dir():
        raise RuntimeError('volume missing')
    if os.environ.get('RAILWAY_ENVIRONMENT'):
        with open('/proc/self/mountinfo', encoding='utf-8') as stream:
            if not any(line.split()[4] == '/data' for line in stream):
                raise RuntimeError('persisted /data volume is not mounted')
    if root.is_symlink() or state.is_symlink():
        raise RuntimeError('unexpected evidence directory symlink')
    os.chown(root, UID, GID, follow_symlinks=False)
    if state.exists():
        paths = [state] + list(state.rglob('*'))
        for path in paths:
            mode = path.lstat().st_mode
            if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
                raise RuntimeError('unsafe file type in evidence volume')
            os.chown(path, UID, GID, follow_symlinks=False)
            os.chmod(path, 0o700 if stat.S_ISDIR(mode) else 0o600, follow_symlinks=False)
    os.setgroups([])
    os.setgid(GID)
    os.setuid(UID)
    if os.geteuid() != UID:
        raise RuntimeError('failed to drop privileges')
    print(json.dumps({'bootstrap': 'volume_owner_verified', 'runtime_uid': os.geteuid()}), flush=True)
    os.execv(sys.executable, [sys.executable, '-u', '/app/worker.py'])


if __name__ == '__main__':
    bootstrap()
