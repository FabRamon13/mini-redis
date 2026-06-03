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

    def test_incrby_creates_key_with_amount(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            server = self.make_server(tmpdir)

            self.assertEqual(server.incrby(b"counter", b"5"), 5)
            self.assertEqual(server.get(b"counter"), b"5")

    def test_incrby_adds_to_existing_integer(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            server = self.make_server(tmpdir)
            server.set(b"counter", b"10")

            self.assertEqual(server.incrby(b"counter", b"7"), 17)
            self.assertEqual(server.get(b"counter"), b"17")

    def test_incrby_supports_zero_amount(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            server = self.make_server(tmpdir)
            server.set(b"counter", b"10")

            self.assertEqual(server.incrby(b"counter", b"0"), 10)
            self.assertEqual(server.get(b"counter"), b"10")

    def test_incrby_supports_negative_amount(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            server = self.make_server(tmpdir)
            server.set(b"counter", b"10")

            self.assertEqual(server.incrby(b"counter", b"-3"), 7)
            self.assertEqual(server.get(b"counter"), b"7")

    def test_incrby_rejects_non_integer_amount(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            server = self.make_server(tmpdir)

            with self.assertRaisesRegex(CommandError, "increment must be an integer"):
                server.incrby(b"counter", b"abc")

            self.assertIsNone(server.get(b"counter"))

    def test_incrby_rejects_non_integer_existing_value(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            server = self.make_server(tmpdir)
            server.set(b"counter", b"hello")

            with self.assertRaisesRegex(CommandError, "value is not an integer"):
                server.incrby(b"counter", b"5")

            self.assertEqual(server.get(b"counter"), b"hello")

    def test_incrby_treats_expired_counter_as_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            server = self.make_server(tmpdir)
            server.set(b"counter", b"10", b"EX", b"1")

            time.sleep(1.01)

            self.assertEqual(server.incrby(b"counter", b"5"), 5)
            self.assertEqual(server.get(b"counter"), b"5")
            self.assertEqual(server.ttl(b"counter"), -1)

    def test_incrby_requires_exactly_two_arguments(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            server = self.make_server(tmpdir)

            with self.assertRaisesRegex(CommandError, "INCRBY requires 2 argument"):
                server.incrby()

            with self.assertRaisesRegex(CommandError, "INCRBY requires 2 argument"):
                server.incrby(b"counter")

            with self.assertRaisesRegex(CommandError, "INCRBY requires 2 argument"):
                server.incrby(b"counter", b"1", b"extra")

    def test_incrby_is_replayed_from_aof(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            server = self.make_server(tmpdir)
            server.incrby(b"counter", b"5")
            server.incrby(b"counter", b"7")

            reloaded = self.make_server(tmpdir)

            self.assertEqual(reloaded.get(b"counter"), b"12")


if __name__ == "__main__":
    unittest.main()
