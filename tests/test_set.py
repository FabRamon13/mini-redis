import tempfile
import unittest

from redis_clone.exceptions import CommandError
from redis_clone.server import Server


class SetTests(unittest.TestCase):
    def make_server(self, tmpdir):
        return Server(port=0, aof_file=f"{tmpdir}/appendonly.aof")

    def assert_invalid_set_preserves_existing_state(self, server, *options):
        server.set(b"counter", b"old", b"EX", b"30")
        original_expiry = server._expiry[b"counter"]

        with self.assertRaises(CommandError):
            server.set(b"counter", b"new", *options)

        self.assertEqual(server.get(b"counter"), b"old")
        self.assertEqual(server._expiry[b"counter"], original_expiry)

    def test_set_rejects_incomplete_options_without_mutation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            server = self.make_server(tmpdir)

            self.assert_invalid_set_preserves_existing_state(server, b"EX")

    def test_set_rejects_unsupported_option_without_mutation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            server = self.make_server(tmpdir)

            self.assert_invalid_set_preserves_existing_state(
                server,
                b"BAD",
                b"30",
            )

    def test_set_rejects_non_numeric_ttl_without_mutation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            server = self.make_server(tmpdir)

            self.assert_invalid_set_preserves_existing_state(
                server,
                b"EX",
                b"invalid",
            )

    def test_set_rejects_non_positive_ttl_without_mutation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            server = self.make_server(tmpdir)

            self.assert_invalid_set_preserves_existing_state(
                server,
                b"EX",
                b"0",
            )

    def test_set_without_expiry_removes_existing_ttl(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            server = self.make_server(tmpdir)
            server.set(b"counter", b"old", b"EX", b"30")

            self.assertEqual(server.set(b"counter", b"new"), 1)
            self.assertEqual(server.get(b"counter"), b"new")
            self.assertEqual(server.ttl(b"counter"), -1)


if __name__ == "__main__":
    unittest.main()
