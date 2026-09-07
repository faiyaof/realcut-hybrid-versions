import tempfile
import unittest
from pathlib import Path


import web_server


class WebQueueLockTests(unittest.TestCase):
    def test_import_does_not_start_or_restore_queue(self):
        self.assertIsNone(web_server.task_queue)

    def test_same_queue_cannot_have_two_owners(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue_file = Path(tmp) / "queue.json"
            first = web_server.QueueFileLease(queue_file)
            second = web_server.QueueFileLease(queue_file)
            first.acquire()
            try:
                with self.assertRaisesRegex(
                    web_server.QueueOwnershipError, "已有 RealCut Hybrid Web 实例占用队列"
                ):
                    second.acquire()
            finally:
                first.release()

            second.acquire()
            second.release()

    def test_different_queue_files_can_be_owned_independently(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = web_server.QueueFileLease(Path(tmp) / "first.json")
            second = web_server.QueueFileLease(Path(tmp) / "second.json")
            first.acquire()
            second.acquire()
            second.release()
            first.release()


if __name__ == "__main__":
    unittest.main()
