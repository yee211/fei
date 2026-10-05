import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fei import config
from fei.changes import apply_change, get_change
from fei.delegation import review_worker
from fei.task_state import TaskState, current_task


class WorkerReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.patch = patch.object(config, 'WORKDIR', self.root)
        self.patch.start()
        self.state = TaskState()
        self.token = current_task.set(self.state)

    def tearDown(self):
        current_task.reset(self.token)
        self.patch.stop()
        self.temp.cleanup()

    def worker(self, ids, status='completed_verified'):
        record = {'id':'worker', 'kind':'worker', 'status':status,
            'review':{'status':'pending'}, 'handoff':{'changes':[{'change_id':ident} for ident in ids]}}
        self.state.subagents.append(record)
        return record

    def test_accept_keeps_bytes_and_cannot_review_twice(self):
        path = self.root / 'file.py'
        ident = apply_change(path, b'new')
        record = self.worker([ident])
        review_worker('worker', 'accept', 'Reviewed diff and child check')
        self.assertEqual(record['review']['status'], 'accepted')
        self.assertEqual(path.read_bytes(), b'new')
        with self.assertRaises(ValueError):
            review_worker('worker', 'reject', 'again')

    def test_reject_restores_multiple_edits_and_removes_new_file(self):
        path = self.root / 'file.py'
        path.write_bytes(b'original')
        ids = [apply_change(path, b'first'), apply_change(path, b'second')]
        new = self.root / 'new.py'
        ids.append(apply_change(new, b'created'))
        self.worker(ids)
        review_worker('worker', 'reject', 'Wrong implementation')
        self.assertEqual(path.read_bytes(), b'original')
        self.assertFalse(new.exists())
        self.assertTrue(all(get_change(ident)['status'] == 'reverted' for ident in ids))

    def test_conflict_refuses_entire_batch(self):
        one, two = self.root / 'one.py', self.root / 'two.py'
        ids = [apply_change(one, b'one'), apply_change(two, b'two')]
        record = self.worker(ids)
        one.write_bytes(b'later edit')
        with self.assertRaises(RuntimeError):
            review_worker('worker', 'reject', 'Reject')
        self.assertEqual(two.read_bytes(), b'two')
        self.assertTrue(all(get_change(ident)['status'] == 'applied' for ident in ids))
        self.assertEqual(record['review']['status'], 'pending')

    def test_failed_child_can_be_rejected_but_not_accepted(self):
        path = self.root / 'file.py'
        ident = apply_change(path, b'partial')
        self.worker([ident], 'failed')
        with self.assertRaises(ValueError):
            review_worker('worker', 'accept', 'Accept')
        review_worker('worker', 'reject', 'Failed check')
        self.assertFalse(path.exists())

    def test_pending_review_blocks_completion(self):
        self.worker([])
        with self.assertRaises(ValueError):
            self.state.finish('done', [], [], [], 'unverified')
        review_worker('worker', 'accept', 'Reviewed no changes')
        self.state.finish('done', [], [], [], 'unverified')

    def test_unknown_child_refused(self):
        with self.assertRaises(ValueError):
            review_worker('missing', 'reject', 'Unknown')


if __name__ == '__main__':
    unittest.main()
