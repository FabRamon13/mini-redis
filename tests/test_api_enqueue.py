import json
import unittest

from fastapi import HTTPException

from fastapi_cache.main import enqueue_job
from redis_clone.exceptions import CommandError


class RecordingCache:
    def __init__(self, error=None):
        self.calls = []
        self.error = error

    def enqueue(self, *args):
        self.calls.append(args)

        if self.error is not None:
            raise self.error

        return b"OK"


class ApiEnqueueTests(unittest.TestCase):
    def test_enqueue_job_uses_atomic_cache_command(self):
        cache = RecordingCache()
        job_data = {"id": "job-1", "status": "queued"}

        enqueue_job(cache, "job-1", "job:job-1", job_data)

        self.assertEqual(len(cache.calls), 1)
        queue_key, job_id, job_key, payload, max_size = cache.calls[0]
        self.assertEqual(queue_key, "jobs")
        self.assertEqual(job_id, "job-1")
        self.assertEqual(job_key, "job:job-1")
        self.assertEqual(json.loads(payload), job_data)
        self.assertGreater(max_size, 0)

    def test_enqueue_job_maps_full_queue_to_http_429(self):
        cache = RecordingCache(CommandError(b"queue is full"))

        with self.assertRaises(HTTPException) as context:
            enqueue_job(cache, "job-1", "job:job-1", {"status": "queued"})

        self.assertEqual(context.exception.status_code, 429)

    def test_enqueue_job_does_not_mask_other_cache_errors(self):
        cache = RecordingCache(CommandError(b"unexpected failure"))

        with self.assertRaisesRegex(CommandError, "unexpected failure"):
            enqueue_job(cache, "job-1", "job:job-1", {"status": "queued"})


if __name__ == "__main__":
    unittest.main()
