import os
import tempfile
import time
import unittest

from redis_clone.exceptions import CommandError
from redis_clone.server import Server


class TtlPersistenceTests(unittest.TestCase):
    def make_server(self, tmpdir):
        return Server(port=0, aof_file=f"{tmpdir}/appendonly.aof")

    def test_reload_preserves_remaining_ttl_instead_of_resetting_duration(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            server = self.make_server(tmpdir)
            server.set(b"temporary", b"value", b"EX", b"0.15")

            time.sleep(0.1)

            reloaded = self.make_server(tmpdir)

            self.assertEqual(reloaded.get(b"temporary"), b"value")
            self.assertLess(reloaded._expiry[b"temporary"] - time.time(), 0.1)

    def test_reload_does_not_restore_already_expired_key(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            server = self.make_server(tmpdir)
            server.set(b"temporary", b"value", b"EX", b"0.01")

            time.sleep(0.02)

            reloaded = self.make_server(tmpdir)

            self.assertIsNone(reloaded.get(b"temporary"))
            self.assertNotIn(b"temporary", reloaded._expiry)

    def test_expireat_sets_absolute_expiration(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            server = self.make_server(tmpdir)
            server.set(b"temporary", b"value")
            expire_at = time.time() + 30

            self.assertEqual(server.expireat(b"temporary", str(expire_at).encode()), 1)
            self.assertEqual(server._expiry[b"temporary"], expire_at)

    def test_expireat_deletes_key_for_past_timestamp(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            server = self.make_server(tmpdir)
            server.set(b"temporary", b"value")

            self.assertEqual(server.expireat(b"temporary", b"0"), 0)
            self.assertIsNone(server.get(b"temporary"))

    def test_expireat_rejects_invalid_timestamp(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            server = self.make_server(tmpdir)
            server.set(b"temporary", b"value")

            for timestamp in (b"invalid", b"nan", b"inf"):
                with self.subTest(timestamp=timestamp):
                    with self.assertRaisesRegex(CommandError, "invalid expire timestamp"):
                        server.expireat(b"temporary", timestamp)

    def test_replay_does_not_append_duplicate_aof_records(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            server = self.make_server(tmpdir)
            server.set(b"temporary", b"value", b"EX", b"30")
            aof_file = f"{tmpdir}/appendonly.aof"
            size_before_reload = os.path.getsize(aof_file)

            self.make_server(tmpdir)

            self.assertEqual(os.path.getsize(aof_file), size_before_reload)


if __name__ == "__main__":
    unittest.main()
