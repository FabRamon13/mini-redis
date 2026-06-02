import tempfile
import unittest

from redis_clone.exceptions import CommandError
from redis_clone.server import Server


class LrangeTests(unittest.TestCase):
    def make_server(self, tmpdir):
        return Server(port=0, aof_file=f"{tmpdir}/appendonly.aof")

    def test_lrange_returns_inclusive_range(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            server = self.make_server(tmpdir)
            server.lpush(b"items", b"one", b"two", b"three")

            self.assertEqual(
                server.lrange(b"items", b"0", b"1"),
                [b"three", b"two"],
            )

    def test_lrange_supports_negative_indices(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            server = self.make_server(tmpdir)
            server.lpush(b"items", b"one", b"two", b"three")

            self.assertEqual(
                server.lrange(b"items", b"0", b"-1"),
                [b"three", b"two", b"one"],
            )
            self.assertEqual(
                server.lrange(b"items", b"-2", b"-1"),
                [b"two", b"one"],
            )

    def test_lrange_returns_empty_list_for_missing_key(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            server = self.make_server(tmpdir)

            self.assertEqual(server.lrange(b"missing", b"0", b"-1"), [])

    def test_lrange_rejects_non_integer_indices(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            server = self.make_server(tmpdir)

            with self.assertRaisesRegex(CommandError, "must be integers"):
                server.lrange(b"items", b"invalid", b"-1")

    def test_lrange_reads_replayed_list(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            server = self.make_server(tmpdir)
            server.lpush(b"items", b"one", b"two")

            reloaded = self.make_server(tmpdir)

            self.assertEqual(
                reloaded.lrange(b"items", b"0", b"-1"),
                [b"two", b"one"],
            )


if __name__ == "__main__":
    unittest.main()
