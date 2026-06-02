import tempfile
import unittest

from redis_clone.server import Server


class PersistenceTests(unittest.TestCase):
    def test_value_survives_server_reload(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            aof_file = f"{tmpdir}/appendonly.aof"
            server = Server(port=0, aof_file=aof_file)
            server.set(b"persistent_name", b"Ramon")

            reloaded = Server(port=0, aof_file=aof_file)

            self.assertEqual(reloaded.get(b"persistent_name"), b"Ramon")


if __name__ == "__main__":
    unittest.main()
