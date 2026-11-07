#!/usr/bin/env python3
"""Isolated, continuous Garcar diagnostic agent: actual scheduled writes, tamper evidence.

Not a shell or a business transaction agent. Operator HMAC grants only authorize one
built-in diagnostic task in this credentialless, non-root worker. Persistent /data required.
"""
import hashlib
import hmac
import json
import os
from pathlib import Path
import platform
import signal
import sqlite3
import subprocess
import sys
import time
import uuid

ROOT = Path('/data')
STATE = ROOT / 'sovereign'
DB = STATE / 'jobs.sqlite3'
AUDIT = STATE / 'audit.jsonl'
REPORT = STATE / 'latest.json'
INTERVAL = 600
MAX_HOURLY = 6
MAX_GRANT_SECONDS = 30 * 86400
STOP = False


def canonical(data):
    return json.dumps(data, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


def sha(data):
    return hashlib.sha256(canonical(data)).hexdigest()


def stop(_signal, _frame):
    global STOP
    STOP = True


def verify_volume():
    # Fail closed if the volume isn't a real mount. Railway environment must not
    # silently write data to the container's ephemeral layer.
    if not ROOT.is_dir() or not os.access(ROOT, os.W_OK):
        raise RuntimeError('Persistent storage /data missing or unwritable')
    if os.environ.get('RAILWAY_ENVIRONMENT'):
        mount = False
        with open('/proc/self/mountinfo', encoding='utf-8') as lines:
            for line in lines:
                fields = line.split()
                if len(fields) > 4 and fields[4] == '/data':
                    mount = True
                    break
        if not mount:
            raise RuntimeError('Railway /data must be a persistent volume mount')
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)


def verify_grant():
    key = os.environ.get('SOVEREIGN_APPROVAL_KEY', '').encode()
    if len(key) < 32:
        raise RuntimeError('Strong independent approval key required')
    try:
        grant = json.loads(os.environ['SOVEREIGN_GRANT_JSON'])
        payload, signature = grant['payload'], grant['signature']
    except (KeyError, ValueError, TypeError) as exc:
        raise RuntimeError('Valid signed operating grant required') from exc
    if not isinstance(payload, dict) or set(payload) != {
        'version', 'task', 'code_sha256', 'issued_at', 'expires_at', 'max_total_runs'
    }:
        raise RuntimeError('Invalid grant scope')
    expected = hmac.new(key, b'garcar-sovereign-stage-v1\0' + canonical(payload), hashlib.sha256).hexdigest()
    if not isinstance(signature, str) or not hmac.compare_digest(signature, expected):
        raise RuntimeError('Grant signature invalid')
    now = int(time.time())
    if (payload['version'] != 1 or payload['task'] != 'environment_report' or
        type(payload['issued_at']) is not int or type(payload['expires_at']) is not int or
        payload['issued_at'] > now + 30 or payload['expires_at'] <= now or
        not 0 < payload['expires_at'] - payload['issued_at'] <= MAX_GRANT_SECONDS or
        type(payload['max_total_runs']) is not int or not 1 <= payload['max_total_runs'] <= 1000):
        raise RuntimeError('Grant expired or exceeds allowed scope')
    actual = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    if not hmac.compare_digest(payload['code_sha256'], actual):
        raise RuntimeError('Executable changed since grant issuance')
    return payload


def verify_audit():
    last = '0' * 64
    count = 0
    if not AUDIT.exists():
        return last, 0
    with AUDIT.open(encoding='utf-8') as inp:
        for line in inp:
            entry = json.loads(line)
            content = {k: v for k, v in entry.items() if k != 'entry_sha256'}
            if entry.get('previous_sha256') != last or entry.get('entry_sha256') != sha(content):
                raise RuntimeError('Audit chain corrupted: halt autonomous execution')
            last = entry['entry_sha256']
            count += 1
    return last, count


def connect_db():
    db = sqlite3.connect(DB, timeout=15, isolation_level=None)
    os.chmod(DB, 0o600)
    check = db.execute('PRAGMA quick_check').fetchone()[0]
    if check != 'ok':
        raise RuntimeError('SQLite integrity check failed')
    db.execute('PRAGMA journal_mode=DELETE')
    db.execute('CREATE TABLE IF NOT EXISTS runs ('
               'run_id TEXT PRIMARY KEY, created_at INTEGER NOT NULL, status TEXT NOT NULL, '
               'receipt_sha256 TEXT)')
    return db


def verify_evidence(db, audit_count):
    """Cross-check every completed SQLite run against an intact audit entry.

    An audit hash chain by itself cannot detect removal of the entire file.
    The independent SQLite ledger and the latest report must agree with it.
    """
    rows = db.execute('SELECT run_id, status, receipt_sha256 FROM runs').fetchall()
    if len(rows) > 1000:
        raise RuntimeError('Run ledger exceeds supported limit')
    if any(status not in ('succeeded', 'reserved') for _, status, _ in rows):
        raise RuntimeError('Run ledger contains invalid status')
    if any(status == 'reserved' for _, status, _ in rows):
        raise RuntimeError('Interrupted execution requires operator reconciliation')
    completed = {run_id: receipt for run_id, _, receipt in rows}
    if len(completed) != audit_count:
        raise RuntimeError('Audit and SQLite run count disagree: halt autonomous execution')
    if not audit_count:
        if REPORT.exists():
            raise RuntimeError('Untracked report exists without audit evidence')
        return
    if not REPORT.exists() or not AUDIT.exists():
        raise RuntimeError('Audit or latest report missing after previous execution')
    latest_entry = None
    with AUDIT.open(encoding='utf-8') as inp:
        for raw in inp:
            entry = json.loads(raw)
            if (entry.get('task') != 'environment_report' or
                    entry.get('state') != 'succeeded' or
                    entry.get('run_id') not in completed):
                raise RuntimeError('Audit entry lacks a matching completed run')
            receipt = {'run_id': entry['run_id'], 'state': 'succeeded',
                       'audit_sha256': entry['entry_sha256']}
            if completed[entry['run_id']] != sha(receipt):
                raise RuntimeError('Audit receipt does not match SQLite ledger')
            latest_entry = entry
    report = json.loads(REPORT.read_text(encoding='utf-8'))
    if (report.get('run_id') != latest_entry['run_id'] or
            sha(report) != latest_entry['report_sha256']):
        raise RuntimeError('Latest report does not match audit evidence')


def safe_write(path, data):
    temp = path.with_name('.' + path.name + '-' + uuid.uuid4().hex)
    try:
        with temp.open('x', encoding='utf-8') as out:
            os.chmod(temp, 0o600)
            json.dump(data, out, sort_keys=True, indent=2)
            out.write('\n')
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def observed_report(run_id):
    cmd = subprocess.run(['git', '--version'], shell=False, capture_output=True,
                         text=True, timeout=10, check=False)
    return {
        'schema_version': 1, 'run_id': run_id, 'timestamp': int(time.time()),
        'observed_python': platform.python_version(),
        'observed_git': cmd.stdout.strip() if cmd.returncode == 0 else None,
        'source': 'actual_staging_process',
        'verified_customer_payments': False,
        'verified_external_agents': False,
    }


def cycle():
    verify_volume()
    previous, audit_count = verify_audit()
    grant = verify_grant()
    with connect_db() as db:
        db.execute('BEGIN IMMEDIATE')
        try:
            verify_evidence(db, audit_count)
            rows = db.execute('SELECT created_at, status FROM runs ORDER BY created_at DESC LIMIT 1000').fetchall()
            if any(status == 'reserved' for _, status in rows):
                raise RuntimeError('Interrupted execution requires operator reconciliation')
            if len(rows) >= grant['max_total_runs']:
                db.execute('COMMIT')
                return {'executed': False, 'reason': 'grant_budget_exhausted'}
            now = int(time.time())
            if rows and now - rows[0][0] < INTERVAL:
                db.execute('COMMIT')
                return {'executed': False, 'reason': 'not_due'}
            if sum(ts > now - 3600 for ts, _ in rows) >= MAX_HOURLY:
                db.execute('COMMIT')
                return {'executed': False, 'reason': 'hourly_budget'}
            run_id = str(uuid.uuid4())
            db.execute("INSERT INTO runs (run_id, created_at, status) VALUES (?, ?, 'reserved')", (run_id, now))
            db.execute('COMMIT')
        except BaseException:
            db.execute('ROLLBACK')
            raise
        report = observed_report(run_id)
        safe_write(REPORT, report)
        entry = {'run_id': run_id, 'task': 'environment_report', 'state': 'succeeded',
                 'previous_sha256': previous, 'report_sha256': sha(report), 'timestamp': int(time.time())}
        entry['entry_sha256'] = sha(entry)
        with AUDIT.open('a', encoding='utf-8') as out:
            os.chmod(AUDIT, 0o600)
            out.write(json.dumps(entry, sort_keys=True) + '\n')
            out.flush()
            os.fsync(out.fileno())
        receipt = {'run_id': run_id, 'state': 'succeeded', 'audit_sha256': entry['entry_sha256']}
        receipt['sha256'] = sha(receipt)
        db.execute("UPDATE runs SET status='succeeded', receipt_sha256=? WHERE run_id=?",
                   (receipt['sha256'], run_id))
        return {'executed': True, 'receipt': receipt}


def main():
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    print(json.dumps({'startup': 'sovereign-staging-worker', 'version': 1}), flush=True)
    while not STOP:
        try:
            result = cycle()
            if result.get('executed') or result.get('reason') != 'not_due':
                print(json.dumps(result, sort_keys=True), flush=True)
        except (RuntimeError, OSError, sqlite3.Error, ValueError, KeyError, subprocess.TimeoutExpired) as exc:
            print(json.dumps({'status': 'PAUSED_FAIL_CLOSED', 'reason': str(exc)}), flush=True)
            return 3
        for _ in range(30):
            if STOP:
                break
            time.sleep(1)
    return 0


if __name__ == '__main__':
    sys.exit(main())
