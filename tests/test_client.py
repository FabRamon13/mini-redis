import os
import time
import unittest

from redis_clone.client import Client


@unittest.skipUnless(
    os.getenv("RUN_INTEGRATION_TESTS") == "1",
    "set RUN_INTEGRATION_TESTS=1 with a running Redis clone",
)
class ClientIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.client = Client()
        self.client.flush()

    def tearDown(self):
        self.client.close()

    def test_key_value_commands(self):
        self.assertEqual(self.client.ping(), b"PONG")
        self.assertEqual(self.client.set("name", "Ramon"), 1)
        self.assertEqual(self.client.get("name"), b"Ramon")
        self.assertEqual(self.client.exists("name"), 1)
        self.assertEqual(self.client.delete("name"), 1)
        self.assertEqual(self.client.get("name"), None)

    def test_multi_key_commands(self):
        self.assertEqual(self.client.mset("k1", "v1", "k2", "v2"), 2)
        self.assertEqual(self.client.mget("k1", "k2"), [b"v1", b"v2"])

    def test_ttl_expiration(self):
        self.assertEqual(self.client.ttl("missing"), -2)
        self.client.set("permanent", "value")
        self.assertEqual(self.client.ttl("permanent"), -1)
        self.client.set("temporary", "value", "EX", "0.01")
        time.sleep(0.02)
        self.assertIsNone(self.client.get("temporary"))


if __name__ == "__main__":
    unittest.main()
