import tempfile
import unittest

from redis_clone.exceptions import CommandError
from redis_clone.server import Server


class FlushTests(unittest.TestCase):
    def make_server(self, tmpdir):
        return Server(port=0, aof_file=f"{tmpdir}/appendonly.aof")

    def test_flush_clears_values_expiry_and_lists(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            server = self.make_server(tmpdir)
            server.set(b"temporary", b"value", b"EX", b"30")
            server.lpush(b"jobs", b"job-1")

            self.assertEqual(server.flush(), 1)

            self.assertIsNone(server.get(b"temporary"))
            self.assertEqual(server.ttl(b"temporary"), -2)
            self.assertEqual(server.llen(b"jobs"), 0)
            self.assertIsNone(server.rpop(b"jobs"))

    def test_flush_requires_no_arguments(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            server = self.make_server(tmpdir)

            with self.assertRaisesRegex(CommandError, "FLUSH requires 0 argument"):
                server.flush(b"unexpected")

    def test_flush_is_replayed_from_aof(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            server = self.make_server(tmpdir)
            server.set(b"stale", b"value")
            server.flush()

            reloaded = self.make_server(tmpdir)

            self.assertIsNone(reloaded.get(b"stale"))


if __name__ == "__main__":
    unittest.main()
