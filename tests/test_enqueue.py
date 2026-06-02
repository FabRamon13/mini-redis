import tempfile
import unittest

from redis_clone.exceptions import CommandError
from redis_clone.server import Server


class EnqueueTests(unittest.TestCase):
    def make_server(self, tmpdir):
        return Server(port=0, aof_file=f"{tmpdir}/appendonly.aof")

    def test_enqueue_stores_metadata_and_pushes_job_id(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            server = self.make_server(tmpdir)

            self.assertEqual(
                server.enqueue(
                    b"jobs",
                    b"job-1",
                    b"job:job-1",
                    b'{"status":"queued"}',
                    b"10",
                ),
                b"OK",
            )

            self.assertEqual(server.get(b"job:job-1"), b'{"status":"queued"}')
            self.assertEqual(server.rpop(b"jobs"), b"job-1")

    def test_enqueue_rejects_full_queue_without_partial_metadata_write(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            server = self.make_server(tmpdir)
            server.enqueue(b"jobs", b"job-1", b"job:job-1", b"first", b"1")

            with self.assertRaisesRegex(CommandError, "queue is full"):
                server.enqueue(b"jobs", b"job-2", b"job:job-2", b"second", b"1")

            self.assertIsNone(server.get(b"job:job-2"))
            self.assertEqual(server.lrange(b"jobs", b"0", b"-1"), [b"job-1"])

    def test_enqueue_rejects_invalid_capacity(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            server = self.make_server(tmpdir)

            for max_size in (b"invalid", b"0", b"-1"):
                with self.subTest(max_size=max_size):
                    with self.assertRaisesRegex(CommandError, "invalid max queue size"):
                        server.enqueue(
                            b"jobs",
                            b"job-1",
                            b"job:job-1",
                            b"payload",
                            max_size,
                        )

    def test_enqueue_is_replayed_from_aof(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            server = self.make_server(tmpdir)
            server.enqueue(b"jobs", b"job-1", b"job:job-1", b"payload", b"10")

            reloaded = self.make_server(tmpdir)

            self.assertEqual(reloaded.get(b"job:job-1"), b"payload")
            self.assertEqual(reloaded.rpop(b"jobs"), b"job-1")


if __name__ == "__main__":
    unittest.main()
