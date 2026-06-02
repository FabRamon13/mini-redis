import os
import unittest

from redis_clone.client import Client


@unittest.skipUnless(
    os.getenv("RUN_INTEGRATION_TESTS") == "1",
    "set RUN_INTEGRATION_TESTS=1 with a running Redis clone",
)
class QueueIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.client = Client()
        self.client.flush()

    def tearDown(self):
        self.client.close()

    def test_lpush_and_rpop_are_fifo(self):
        self.assertEqual(self.client.llen("jobs"), 0)
        self.assertEqual(self.client.lpush("jobs", "job1"), 1)
        self.assertEqual(self.client.lpush("jobs", "job2"), 2)
        self.assertEqual(self.client.rpop("jobs"), b"job1")
        self.assertEqual(self.client.rpop("jobs"), b"job2")
        self.assertIsNone(self.client.rpop("jobs"))


if __name__ == "__main__":
    unittest.main()
