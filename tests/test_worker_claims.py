import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from worker.worker import load_positive_int
from worker.worker import process_claimed_job
from worker.worker import recover_stale_processing_jobs


class MemoryQueueClient:
    def __init__(self):
        self.data = {}
        self.lists = {}

    def get(self, key):
        value = self.data.get(key)
        return value.encode("utf-8") if value is not None else None

    def set(self, key, value, *options):
        self.data[key] = value
        return 1

    def incr(self, key):
        value = int(self.data.get(key, "0")) + 1
        self.data[key] = str(value)
        return value

    def lpush(self, key, *values):
        items = self.lists.setdefault(key, [])

        for value in values:
            items.insert(0, value)

        return len(items)

    def lrem(self, key, value):
        items = self.lists.get(key, [])
        new_items = [item for item in items if item != value]
        self.lists[key] = new_items
        return len(items) - len(new_items)

    def lrange(self, key, start, stop):
        items = self.lists.get(key, [])

        if stop == -1:
            stop = len(items) - 1

        return items[start:stop + 1]

    def ack(self, key, value, claim_token=""):
        self.data.pop(f"worker_claim:{value}", None)
        return self.lrem(key, value)

    def requeue(self, source, destination, job_id, job_key, job_payload, claim_token=""):
        removed = self.lrem(source, job_id)

        if not removed:
            return 0

        destination_items = self.lists.setdefault(destination, [])

        if job_id not in destination_items:
            destination_items.insert(0, job_id)

        self.data[job_key] = job_payload
        self.data.pop(f"worker_claim:{job_id}", None)
        return removed

    def finish(self, source, destination, job_id, job_key, job_payload, claim_token=""):
        removed = self.lrem(source, job_id)

        if not removed:
            return 0

        if destination:
            destination_items = self.lists.setdefault(destination, [])

            if job_id not in destination_items:
                destination_items.insert(0, job_id)

        self.data[job_key] = job_payload
        self.data.pop(f"worker_claim:{job_id}", None)
        return removed

    def update_claim(self, job_id, job_key, job_payload, claim_token=""):
        self.data[job_key] = job_payload
        return 1


class WorkerClaimTests(unittest.TestCase):
    def make_job(self, attempts=0, max_attempts=3):
        return {
            "id": "job-1",
            "status": "queued",
            "type": "demo_task",
            "attempts": attempts,
            "max_attempts": max_attempts,
            "started_at": None,
            "completed_at": None,
            "failed_at": None,
            "error": None,
            "result": None,
        }

    def make_client(self, job=None):
        client = MemoryQueueClient()
        client.lpush("processing_jobs", "job-1")

        if job is not None:
            client.set("job:job-1", json.dumps(job))

        return client

    def test_completed_job_is_acknowledged(self):
        client = self.make_client(self.make_job())

        with patch("worker.worker.process_job", return_value={"ok": True}):
            process_claimed_job(client, "job-1", "worker-1")

        job = json.loads(client.data["job:job-1"])
        self.assertEqual(job["status"], "completed")
        self.assertEqual(job["result"], {"ok": True})
        self.assertEqual(client.lists["processing_jobs"], [])
        self.assertEqual(client.data["metrics:processed_jobs"], "1")
        self.assertIn("claimed_at", job)
        self.assertIn("lease_seconds", job)

    def test_retry_requeues_and_acknowledges_current_claim(self):
        client = self.make_client(self.make_job())

        with patch("worker.worker.process_job", side_effect=RuntimeError("failed")):
            process_claimed_job(client, "job-1", "worker-1")

        job = json.loads(client.data["job:job-1"])
        self.assertEqual(job["status"], "queued")
        self.assertEqual(job["attempts"], 1)
        self.assertEqual(client.lists["jobs"], ["job-1"])
        self.assertEqual(client.lists["processing_jobs"], [])

    def test_final_failure_moves_to_dead_queue_and_acknowledges_claim(self):
        client = self.make_client(self.make_job(attempts=2))

        with patch("worker.worker.process_job", side_effect=RuntimeError("failed")):
            process_claimed_job(client, "job-1", "worker-1")

        job = json.loads(client.data["job:job-1"])
        self.assertEqual(job["status"], "failed")
        self.assertEqual(job["attempts"], 3)
        self.assertEqual(client.lists["dead_jobs"], ["job-1"])
        self.assertEqual(client.lists["processing_jobs"], [])
        self.assertEqual(client.data["metrics:failed_jobs"], "1")

    def test_missing_job_metadata_removes_stale_claim(self):
        client = self.make_client()

        process_claimed_job(client, "job-1", "worker-1")

        self.assertEqual(client.lists["processing_jobs"], [])


class WorkerLeaseRecoveryTests(unittest.TestCase):
    def make_client(self, claimed_at, lease_seconds=60):
        client = MemoryQueueClient()
        client.lpush("processing_jobs", "job-1")
        client.set("job:job-1", json.dumps({
            "id": "job-1",
            "status": "running",
            "claimed_at": claimed_at,
            "lease_seconds": lease_seconds,
            "worker_id": "worker-1",
            "started_at": claimed_at,
        }))
        return client

    def test_positive_int_loader_accepts_positive_integer(self):
        self.assertEqual(load_positive_int("LEASE", 60, "2"), 2)

    def test_positive_int_loader_rejects_invalid_boundaries(self):
        for value in ("invalid", "1.5", "0", "-1"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    load_positive_int("LEASE", 60, value)

    def test_stale_job_is_requeued_and_metadata_is_reset(self):
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        client = self.make_client((now - timedelta(seconds=61)).isoformat())

        self.assertEqual(recover_stale_processing_jobs(client, now=now), 1)

        job = json.loads(client.data["job:job-1"])
        self.assertEqual(client.lists["processing_jobs"], [])
        self.assertEqual(client.lists["jobs"], ["job-1"])
        self.assertEqual(job["status"], "queued")
        self.assertIsNone(job["worker_id"])
        self.assertIsNone(job["claimed_at"])
        self.assertEqual(job["error"], "Recovered from stale worker claim")

    def test_job_at_exact_lease_boundary_is_not_requeued(self):
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        client = self.make_client((now - timedelta(seconds=60)).isoformat())

        self.assertEqual(recover_stale_processing_jobs(client, now=now), 0)
        self.assertEqual(client.lists["processing_jobs"], ["job-1"])

    def test_fresh_job_is_not_requeued(self):
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        client = self.make_client((now - timedelta(seconds=59)).isoformat())

        self.assertEqual(recover_stale_processing_jobs(client, now=now), 0)
        self.assertEqual(client.lists["processing_jobs"], ["job-1"])

    def test_second_recovery_scan_does_not_duplicate_job(self):
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        client = self.make_client((now - timedelta(seconds=61)).isoformat())

        self.assertEqual(recover_stale_processing_jobs(client, now=now), 1)
        self.assertEqual(recover_stale_processing_jobs(client, now=now), 0)
        self.assertEqual(client.lists["jobs"], ["job-1"])

    def test_atomic_claim_marker_recovers_crash_before_job_metadata_update(self):
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        client = self.make_client(None)
        client.set("worker_claim:job-1", json.dumps({
            "worker_id": "worker-1",
            "claim_token": "claim-1",
            "claimed_at": (now - timedelta(seconds=61)).isoformat(),
            "lease_seconds": 60,
        }))

        self.assertEqual(recover_stale_processing_jobs(client, now=now), 1)
        self.assertEqual(client.lists["processing_jobs"], [])
        self.assertEqual(client.lists["jobs"], ["job-1"])
        self.assertNotIn("worker_claim:job-1", client.data)

    def test_missing_metadata_removes_orphaned_processing_claim(self):
        client = MemoryQueueClient()
        client.lpush("processing_jobs", "job-1")

        self.assertEqual(recover_stale_processing_jobs(client), 0)
        self.assertEqual(client.lists["processing_jobs"], [])

    def test_malformed_timestamp_does_not_requeue_or_crash(self):
        client = self.make_client("not-a-timestamp")

        self.assertEqual(recover_stale_processing_jobs(client), 0)
        self.assertEqual(client.lists["processing_jobs"], ["job-1"])

    def test_naive_timestamp_does_not_requeue_or_crash(self):
        client = self.make_client("2026-01-01T00:00:00")

        self.assertEqual(recover_stale_processing_jobs(client), 0)
        self.assertEqual(client.lists["processing_jobs"], ["job-1"])

    def test_invalid_job_lease_does_not_requeue_or_crash(self):
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        client = self.make_client(
            (now - timedelta(seconds=61)).isoformat(),
            lease_seconds=0,
        )

        self.assertEqual(recover_stale_processing_jobs(client, now=now), 0)
        self.assertEqual(client.lists["processing_jobs"], ["job-1"])


if __name__ == "__main__":
    unittest.main()
