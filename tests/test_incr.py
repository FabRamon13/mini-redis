import tempfile
import time
import unittest

from redis_clone.exceptions import CommandError
from redis_clone.server import Server


class IncrTests(unittest.TestCase):
    def make_server(self, tmpdir):
        return Server(port=0, aof_file=f"{tmpdir}/appendonly.aof")

    def test_incr_initializes_and_increments_counter(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            server = self.make_server(tmpdir)

            self.assertEqual(server.incr(b"counter"), 1)
            self.assertEqual(server.incr(b"counter"), 2)
            self.assertEqual(server.get(b"counter"), b"2")

    def test_incr_rejects_non_integer_value(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            server = self.make_server(tmpdir)
            server.set(b"counter", b"invalid")

            with self.assertRaisesRegex(CommandError, "value is not an integer"):
                server.incr(b"counter")

            self.assertEqual(server.get(b"counter"), b"invalid")

    def test_incr_treats_expired_counter_as_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            server = self.make_server(tmpdir)
            server.set(b"counter", b"10", b"EX", b"0.01")

            time.sleep(0.02)

            self.assertEqual(server.incr(b"counter"), 1)
            self.assertEqual(server.get(b"counter"), b"1")
            self.assertEqual(server.ttl(b"counter"), -1)

    def test_incr_requires_exactly_one_argument(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            server = self.make_server(tmpdir)

            with self.assertRaisesRegex(CommandError, "INCR requires 1 argument"):
                server.incr()

            with self.assertRaisesRegex(CommandError, "INCR requires 1 argument"):
                server.incr(b"counter", b"extra")

    def test_incr_is_replayed_from_aof(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            server = self.make_server(tmpdir)
            server.incr(b"counter")
            server.incr(b"counter")

            reloaded = self.make_server(tmpdir)

            self.assertEqual(reloaded.get(b"counter"), b"2")
            self.assertEqual(reloaded.incr(b"counter"), 3)


if __name__ == "__main__":
    unittest.main()
