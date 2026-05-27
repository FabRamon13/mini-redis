import tempfile
import unittest

from server import Server


class AOFTests(unittest.TestCase):
    def test_resp_aof_preserves_spaces_in_values(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            aof_file = f"{tmpdir}/appendonly.aof"

            server = Server(port=0, aof_file=aof_file)
            server.set(b"message", b"hello world")

            reloaded = Server(port=0, aof_file=aof_file)

            self.assertEqual(reloaded.get(b"message"), b"hello world")


if __name__ == "__main__":
    unittest.main()
