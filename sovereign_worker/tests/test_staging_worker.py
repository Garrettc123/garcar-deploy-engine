"""Standalone tests for the actual staging worker; no Railway or real secrets required."""
import hashlib
import hmac
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
WORKER = ROOT / 'sovereign_worker' / 'worker.py'
spec = importlib.util.spec_from_file_location('staging_worker', WORKER)
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.state = self.base / 'sovereign'
        self.state.mkdir()
        self.patchers = [
            patch.object(worker, 'ROOT', self.base),
            patch.object(worker, 'STATE', self.state),
            patch.object(worker, 'DB', self.state / 'jobs.sqlite3'),
            patch.object(worker, 'AUDIT', self.state / 'audit.jsonl'),
            patch.object(worker, 'REPORT', self.state / 'latest.json'),
            patch.dict(os.environ, {'SOVEREIGN_APPROVAL_KEY': 'only-a-fixture-key-with-adequate-length-12345'}, clear=True),
        ]
        for p in self.patchers:
            p.start()
            self.addCleanup(p.stop)
        self.key = os.environ['SOVEREIGN_APPROVAL_KEY'].encode()
        self.make_grant()

    def make_grant(self, **updates):
        now = int(time.time())
        payload = dict(version=1, task='environment_report',
                       code_sha256=hashlib.sha256(WORKER.read_bytes()).hexdigest(),
                       issued_at=now-30, expires_at=now+300,
                       max_total_runs=10)
        payload.update(updates)
        sig = hmac.new(self.key, b'garcar-sovereign-stage-v1\0'+worker.canonical(payload), hashlib.sha256).hexdigest()
        os.environ['SOVEREIGN_GRANT_JSON'] = json.dumps({'payload':payload,'signature':sig})

    def test_runs_real_report_and_ledger(self):
        r=worker.cycle()
        self.assertTrue(r['executed'])
        self.assertEqual(json.loads(worker.REPORT.read_text())['run_id'],r['receipt']['run_id'])
        self.assertEqual(worker.verify_audit()[1],1)
        with sqlite3.connect(worker.DB) as db:
            self.assertEqual(db.execute("select status from runs").fetchone()[0], 'succeeded')

    def test_rejects_early_second_run(self):
        self.assertTrue(worker.cycle()['executed'])
        self.assertEqual(worker.cycle(),{'executed':False,'reason':'not_due'})

    def test_bad_signature_fails_closed(self):
        original=json.loads(os.environ['SOVEREIGN_GRANT_JSON'])
        original['payload']['max_total_runs']=999
        os.environ['SOVEREIGN_GRANT_JSON']=json.dumps(original)
        with self.assertRaisesRegex(RuntimeError,'signature'):
            worker.cycle()

    def test_code_digest_cannot_be_forged_by_grant(self):
        self.make_grant(code_sha256='f'*64)
        with self.assertRaisesRegex(RuntimeError,'Executable changed'):
            worker.cycle()

    def test_expired_grant_fails_closed(self):
        now = int(time.time())
        self.make_grant(issued_at=now-150, expires_at=now-1)
        with self.assertRaisesRegex(RuntimeError,'Grant expired'):
            worker.cycle()

    def test_corrupted_audit_blocks_future_execution(self):
        self.assertTrue(worker.cycle()['executed'])
        with worker.AUDIT.open('a') as out:
            out.write('{"bad":true}\n')
        with self.assertRaisesRegex(RuntimeError,'Audit chain corrupted'):
            worker.cycle()

    def test_reserved_execution_blocks_duplicate(self):
        worker.connect_db().close()
        with sqlite3.connect(worker.DB) as db:
            db.execute("insert into runs(run_id,created_at,status) values('orphan',1,'reserved')")
        with self.assertRaisesRegex(RuntimeError,'Interrupted execution'):
            worker.cycle()

    def test_missing_audit_after_success_blocks_new_execution(self):
        self.assertTrue(worker.cycle()['executed'])
        worker.AUDIT.unlink()
        with self.assertRaisesRegex(RuntimeError,'Audit'):
            worker.cycle()

    def test_unchanged_evidence_survives_repeated_cycles(self):
        self.assertTrue(worker.cycle()['executed'])
        self.assertEqual(worker.cycle()['reason'], 'not_due')
        self.assertEqual(worker.verify_audit()[1], 1)

    def test_missing_report_fails_closed(self):
        self.assertTrue(worker.cycle()['executed'])
        worker.REPORT.unlink()
        with self.assertRaisesRegex(RuntimeError, 'report missing'):
            worker.cycle()

    def test_corrupted_report_fails_closed(self):
        self.assertTrue(worker.cycle()['executed'])
        report=json.loads(worker.REPORT.read_text())
        report['verified_customer_payments']=True
        worker.REPORT.write_text(json.dumps(report))
        with self.assertRaisesRegex(RuntimeError, 'does not match audit'):
            worker.cycle()

    def test_sqlite_receipt_tampering_fails_closed(self):
        self.assertTrue(worker.cycle()['executed'])
        with sqlite3.connect(worker.DB) as db:
            db.execute("update runs set receipt_sha256=?", ('f'*64,))
        with self.assertRaisesRegex(RuntimeError, 'receipt does not match'):
            worker.cycle()

    def test_deleting_all_sqlite_rows_fails_closed(self):
        self.assertTrue(worker.cycle()['executed'])
        with sqlite3.connect(worker.DB) as db:
            db.execute('delete from runs')
        with self.assertRaisesRegex(RuntimeError, 'Audit and SQLite run count disagree'):
            worker.cycle()

    def test_later_run_preserves_complete_evidence(self):
        self.assertTrue(worker.cycle()['executed'])
        with patch.object(worker,'INTERVAL',0):
            result=worker.cycle()
        self.assertTrue(result['executed'])
        self.assertEqual(worker.verify_audit()[1],2)
        self.assertEqual(worker.cycle()['reason'],'not_due')

    def test_budget_ceiling(self):
        self.make_grant(max_total_runs=1)
        self.assertTrue(worker.cycle()['executed'])
        self.assertEqual(worker.cycle(),{'executed':False,'reason':'grant_budget_exhausted'})

if __name__=='__main__': unittest.main()
