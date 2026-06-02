import tempfile
import unittest

from redis_clone.server import Server


class QueuePersistenceTests(unittest.TestCase):
    def make_server(self, tmpdir):
        return Server(port=0, aof_file=f"{tmpdir}/appendonly.aof")

    def test_lpush_queue_order_is_replayed_from_aof(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            server = self.make_server(tmpdir)
            server.lpush(b"jobs", b"job-1")
            server.lpush(b"jobs", b"job-2")

            reloaded = self.make_server(tmpdir)

            self.assertEqual(reloaded.rpop(b"jobs"), b"job-1")
            self.assertEqual(reloaded.rpop(b"jobs"), b"job-2")
            self.assertIsNone(reloaded.rpop(b"jobs"))

    def test_consumed_job_does_not_reappear_after_reload(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            server = self.make_server(tmpdir)
            server.lpush(b"jobs", b"job-1")
            self.assertEqual(server.rpop(b"jobs"), b"job-1")

            reloaded = self.make_server(tmpdir)

            self.assertIsNone(reloaded.rpop(b"jobs"))

    def test_multi_value_lpush_is_replayed_from_aof(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            server = self.make_server(tmpdir)
            self.assertEqual(
                server.lpush(b"jobs", b"job-1", b"job-2"),
                2,
            )

            reloaded = self.make_server(tmpdir)

            self.assertEqual(reloaded.rpop(b"jobs"), b"job-1")
            self.assertEqual(reloaded.rpop(b"jobs"), b"job-2")

    def test_flush_removes_replayed_queue_entries(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            server = self.make_server(tmpdir)
            server.lpush(b"jobs", b"job-1")
            server.flush()

            reloaded = self.make_server(tmpdir)

            self.assertEqual(reloaded.llen(b"jobs"), 0)
            self.assertIsNone(reloaded.rpop(b"jobs"))


if __name__ == "__main__":
    unittest.main()
