import json
import unittest
from types import SimpleNamespace

from fastapi import HTTPException

from fastapi_cache.main import enqueue_job
from fastapi_cache.main import get_job_metrics
from fastapi_cache.main import prometheus_metrics
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


class MetricsCache:
    def __init__(self):
        self.values = {
            "metrics:processed_jobs": b"3",
            "metrics:failed_jobs": b"1",
            "metrics:semantic_cache_hits": b"2",
            "metrics:semantic_cache_misses": b"1",
            "metrics:faiss_search_count": b"5",
            "metrics:linear_search_count": b"7",
            "metrics:faiss_search_latency_ms_total": b"25",
            "metrics:linear_search_latency_ms_total": b"35",
            "metrics:provider_call_count": b"4",
            "metrics:provider_latency_ms_total": b"44",
        }
        self.lists = {
            "jobs": 4,
            "processing_jobs": 2,
            "dead_jobs": 1,
        }

    def get(self, key):
        return self.values.get(key)

    def llen(self, key):
        return self.lists.get(key, 0)


class CorruptMetricsCache(MetricsCache):
    def __init__(self):
        super().__init__()
        self.values = {
            "metrics:processed_jobs": b"not-an-int",
            "metrics:failed_jobs": "not-bytes",
            "metrics:semantic_cache_hits": b"\xff",
            "metrics:semantic_cache_misses": b"bad",
            "metrics:faiss_search_count": b"bad",
            "metrics:linear_search_count": b"bad",
            "metrics:faiss_search_latency_ms_total": b"bad",
            "metrics:linear_search_latency_ms_total": b"bad",
            "metrics:provider_call_count": b"bad",
            "metrics:provider_latency_ms_total": b"bad",
        }


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

    def test_job_metrics_include_atomic_search_counters(self):
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(cache=MetricsCache())))

        metrics = get_job_metrics(request)

        self.assertEqual(metrics["processed_jobs"], 3)
        self.assertEqual(metrics["processing_jobs"], 2)
        self.assertEqual(metrics["failed_jobs"], 1)
        self.assertEqual(metrics["semantic_cache_hits"], 2)
        self.assertEqual(metrics["semantic_cache_misses"], 1)
        self.assertEqual(metrics["faiss_search_count"], 5)
        self.assertEqual(metrics["faiss_search_latency_ms_total"], 25)
        self.assertEqual(metrics["faiss_search_latency_ms_avg"], 5.0)
        self.assertEqual(metrics["linear_search_count"], 7)
        self.assertEqual(metrics["linear_search_latency_ms_total"], 35)
        self.assertEqual(metrics["linear_search_latency_ms_avg"], 5.0)
        self.assertEqual(metrics["provider_call_count"], 4)
        self.assertEqual(metrics["provider_latency_ms_total"], 44)
        self.assertEqual(metrics["provider_latency_ms_avg"], 11.0)

    def test_prometheus_metrics_returns_plaintext_metrics(self):
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(cache=MetricsCache())))

        response = prometheus_metrics(request)

        self.assertIn("mini_redis_queued_jobs 4", response)
        self.assertIn("mini_redis_processing_jobs 2", response)
        self.assertIn("mini_redis_semantic_cache_hits 2", response)
        self.assertIn("mini_redis_faiss_search_latency_ms_avg 5.0", response)
        self.assertIn("mini_redis_provider_latency_ms_avg 11.0", response)
        self.assertTrue(response.endswith("\n"))

    def test_job_metrics_treat_corrupt_counters_as_zero(self):
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(cache=CorruptMetricsCache())))

        metrics = get_job_metrics(request)

        self.assertEqual(metrics["processed_jobs"], 0)
        self.assertEqual(metrics["failed_jobs"], 0)
        self.assertEqual(metrics["semantic_cache_hits"], 0)
        self.assertEqual(metrics["semantic_cache_misses"], 0)
        self.assertEqual(metrics["semantic_cache_hit_rate"], 0)
        self.assertEqual(metrics["faiss_search_count"], 0)
        self.assertEqual(metrics["faiss_search_latency_ms_total"], 0)
        self.assertEqual(metrics["faiss_search_latency_ms_avg"], 0)
        self.assertEqual(metrics["linear_search_count"], 0)
        self.assertEqual(metrics["linear_search_latency_ms_total"], 0)
        self.assertEqual(metrics["linear_search_latency_ms_avg"], 0)
        self.assertEqual(metrics["provider_call_count"], 0)
        self.assertEqual(metrics["provider_latency_ms_total"], 0)
        self.assertEqual(metrics["provider_latency_ms_avg"], 0)

    def test_prometheus_metrics_treat_corrupt_counters_as_zero(self):
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(cache=CorruptMetricsCache())))

        response = prometheus_metrics(request)

        self.assertIn("mini_redis_processed_jobs 0", response)
        self.assertIn("mini_redis_semantic_cache_hits 0", response)
        self.assertIn("mini_redis_faiss_search_latency_ms_avg 0", response)
        self.assertIn("mini_redis_provider_latency_ms_avg 0", response)


if __name__ == "__main__":
    unittest.main()
