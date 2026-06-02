from concurrent.futures import ThreadPoolExecutor
import os
import unittest

from redis_clone.client import Client


@unittest.skipUnless(
    os.getenv("RUN_INTEGRATION_TESTS") == "1",
    "set RUN_INTEGRATION_TESTS=1 with a running Redis clone",
)
class ConcurrencyIntegrationTests(unittest.TestCase):
    def setUp(self):
        client = Client()
        client.flush()
        client.close()

    def test_concurrent_clients(self):
        def write_and_read(index):
            client = Client()

            try:
                key = f"user:{index}"
                value = f"value:{index}"
                self.assertEqual(client.set(key, value), 1)
                self.assertEqual(client.get(key), value.encode())
            finally:
                client.close()

        with ThreadPoolExecutor(max_workers=10) as executor:
            list(executor.map(write_and_read, range(50)))


if __name__ == "__main__":
    unittest.main()
