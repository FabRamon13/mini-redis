import tempfile
import unittest

from redis_clone.server import Server


class AOFTests(unittest.TestCase):
    def test_resp_aof_preserves_spaces_in_values(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            aof_file = f"{tmpdir}/appendonly.aof"

            server = Server(port=0, aof_file=aof_file)
            server.set(b"message", b"hello world")

            reloaded = Server(port=0, aof_file=aof_file)

            self.assertEqual(reloaded.get(b"message"), b"hello world")

    def test_replay_stops_before_truncated_final_record(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            aof_file = f"{tmpdir}/appendonly.aof"

            server = Server(port=0, aof_file=aof_file)
            server.set(b"good", b"value")

            with open(aof_file, "ab") as f:
                f.write(
                    b"*3\r\n"
                    b"$3\r\nSET\r\n"
                    b"$3\r\nbad\r\n"
                    b"$5\r\npa"
                )

            reloaded = Server(port=0, aof_file=aof_file)

            self.assertEqual(reloaded.get(b"good"), b"value")
            self.assertIsNone(reloaded.get(b"bad"))


if __name__ == "__main__":
    unittest.main()
