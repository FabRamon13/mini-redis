import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor

from redis_clone.exceptions import CommandError
from redis_clone.server import Server


class ReliableQueueTests(unittest.TestCase):
    def make_server(self, tmpdir):
        return Server(port=0, aof_file=f"{tmpdir}/appendonly.aof")

    def test_rpoplpush_moves_oldest_job_into_processing_queue(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            server = self.make_server(tmpdir)
            server.lpush(b"jobs", b"job-1")
            server.lpush(b"jobs", b"job-2")

            self.assertEqual(
                server.rpoplpush(b"jobs", b"processing_jobs"),
                b"job-1",
            )
            self.assertEqual(server.lrange(b"jobs", b"0", b"-1"), [b"job-2"])
            self.assertEqual(
                server.lrange(b"processing_jobs", b"0", b"-1"),
                [b"job-1"],
            )

    def test_lrem_acknowledges_processing_job(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            server = self.make_server(tmpdir)
            server.lpush(b"processing_jobs", b"job-1")

            self.assertEqual(server.lrem(b"processing_jobs", b"job-1"), 1)
            self.assertEqual(server.lrange(b"processing_jobs", b"0", b"-1"), [])
            self.assertEqual(server.lrem(b"processing_jobs", b"job-1"), 0)

    def test_claim_and_ack_are_replayed_from_aof(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            server = self.make_server(tmpdir)
            server.lpush(b"jobs", b"job-1")
            server.rpoplpush(b"jobs", b"processing_jobs")
            server.lrem(b"processing_jobs", b"job-1")

            reloaded = self.make_server(tmpdir)

            self.assertEqual(reloaded.lrange(b"jobs", b"0", b"-1"), [])
            self.assertEqual(reloaded.lrange(b"processing_jobs", b"0", b"-1"), [])

    def test_unacknowledged_claim_remains_visible_after_reload(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            server = self.make_server(tmpdir)
            server.lpush(b"jobs", b"job-1")
            server.rpoplpush(b"jobs", b"processing_jobs")

            reloaded = self.make_server(tmpdir)

            self.assertEqual(
                reloaded.lrange(b"processing_jobs", b"0", b"-1"),
                [b"job-1"],
            )

    def test_claim_atomically_moves_job_and_records_lease(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            server = self.make_server(tmpdir)
            server.lpush(b"jobs", b"job-1")

            self.assertEqual(
                server.claim(
                    b"jobs",
                    b"processing_jobs",
                    b"worker-1",
                    b"claim-1",
                    b"2026-01-01T00:00:00+00:00",
                    b"60",
                ),
                b"job-1",
            )

            claim = json.loads(server.get(b"worker_claim:job-1"))
            self.assertEqual(claim["worker_id"], "worker-1")
            self.assertEqual(claim["claim_token"], "claim-1")
            self.assertEqual(claim["lease_seconds"], 60)
            self.assertEqual(server.lrange(b"jobs", b"0", b"-1"), [])
            self.assertEqual(
                server.lrange(b"processing_jobs", b"0", b"-1"),
                [b"job-1"],
            )

    def test_claim_rejects_invalid_lease_without_moving_job(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            server = self.make_server(tmpdir)
            server.lpush(b"jobs", b"job-1")

            for lease_seconds in (b"invalid", b"0", b"-1"):
                with self.subTest(lease_seconds=lease_seconds):
                    with self.assertRaises(CommandError):
                        server.claim(
                            b"jobs",
                            b"processing_jobs",
                            b"worker-1",
                            b"claim-1",
                            b"2026-01-01T00:00:00+00:00",
                            lease_seconds,
                        )

            self.assertEqual(server.lrange(b"jobs", b"0", b"-1"), [b"job-1"])
            self.assertEqual(server.lrange(b"processing_jobs", b"0", b"-1"), [])

    def test_requeue_is_atomic_and_duplicate_resistant(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            server = self.make_server(tmpdir)
            server.lpush(b"processing_jobs", b"job-1")
            server.lpush(b"jobs", b"job-1")
            server.set(b"worker_claim:job-1", b'{"claim_token":""}')

            self.assertEqual(
                server.requeue(
                    b"processing_jobs",
                    b"jobs",
                    b"job-1",
                    b"job:job-1",
                    b'{"status":"queued"}',
                    b"",
                ),
                1,
            )
            self.assertEqual(
                server.requeue(
                    b"processing_jobs",
                    b"jobs",
                    b"job-1",
                    b"job:job-1",
                    b'{"status":"queued"}',
                    b"",
                ),
                0,
            )
            self.assertEqual(server.lrange(b"jobs", b"0", b"-1"), [b"job-1"])
            self.assertIsNone(server.get(b"worker_claim:job-1"))

    def test_concurrent_requeue_attempts_only_move_job_once(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            server = self.make_server(tmpdir)
            server.lpush(b"processing_jobs", b"job-1")

            def requeue():
                return server.requeue(
                    b"processing_jobs",
                    b"jobs",
                    b"job-1",
                    b"job:job-1",
                    b'{"status":"queued"}',
                    b"",
                )

            with ThreadPoolExecutor(max_workers=8) as executor:
                results = list(executor.map(lambda _: requeue(), range(32)))

            self.assertEqual(sum(results), 1)
            self.assertEqual(server.lrange(b"processing_jobs", b"0", b"-1"), [])
            self.assertEqual(server.lrange(b"jobs", b"0", b"-1"), [b"job-1"])

    def test_ack_removes_processing_job_and_claim_marker(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            server = self.make_server(tmpdir)
            server.lpush(b"processing_jobs", b"job-1")
            server.set(b"worker_claim:job-1", b'{"claim_token":""}')

            self.assertEqual(server.ack(b"processing_jobs", b"job-1", b""), 1)
            self.assertEqual(server.lrange(b"processing_jobs", b"0", b"-1"), [])
            self.assertIsNone(server.get(b"worker_claim:job-1"))

    def test_stale_worker_token_cannot_ack_newer_claim(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            server = self.make_server(tmpdir)
            server.lpush(b"jobs", b"job-1")
            server.claim(
                b"jobs",
                b"processing_jobs",
                b"worker-1",
                b"claim-1",
                b"2026-01-01T00:00:00+00:00",
                b"60",
            )
            server.requeue(
                b"processing_jobs",
                b"jobs",
                b"job-1",
                b"job:job-1",
                b'{"status":"queued"}',
                b"claim-1",
            )
            server.claim(
                b"jobs",
                b"processing_jobs",
                b"worker-2",
                b"claim-2",
                b"2026-01-01T00:01:00+00:00",
                b"60",
            )

            self.assertEqual(
                server.update_claim(
                    b"job-1",
                    b"job:job-1",
                    b'{"status":"running","worker_id":"worker-1"}',
                    b"claim-1",
                ),
                0,
            )
            self.assertEqual(server.ack(b"processing_jobs", b"job-1", b"claim-1"), 0)
            self.assertEqual(
                server.requeue(
                    b"processing_jobs",
                    b"jobs",
                    b"job-1",
                    b"job:job-1",
                    b'{"status":"queued"}',
                    b"claim-1",
                ),
                0,
            )
            self.assertEqual(
                server.finish(
                    b"processing_jobs",
                    b"",
                    b"job-1",
                    b"job:job-1",
                    b'{"status":"completed"}',
                    b"claim-1",
                ),
                0,
            )
            self.assertEqual(
                server.lrange(b"processing_jobs", b"0", b"-1"),
                [b"job-1"],
            )
            claim = json.loads(server.get(b"worker_claim:job-1"))
            self.assertEqual(claim["claim_token"], "claim-2")

    def test_finish_atomically_persists_result_and_acknowledges_claim(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            server = self.make_server(tmpdir)
            server.lpush(b"jobs", b"job-1")
            server.claim(
                b"jobs",
                b"processing_jobs",
                b"worker-1",
                b"claim-1",
                b"2026-01-01T00:00:00+00:00",
                b"60",
            )

            self.assertEqual(
                server.finish(
                    b"processing_jobs",
                    b"",
                    b"job-1",
                    b"job:job-1",
                    b'{"status":"completed"}',
                    b"claim-1",
                ),
                1,
            )
            self.assertEqual(server.get(b"job:job-1"), b'{"status":"completed"}')
            self.assertEqual(server.lrange(b"processing_jobs", b"0", b"-1"), [])
            self.assertIsNone(server.get(b"worker_claim:job-1"))

            reloaded = self.make_server(tmpdir)
            self.assertEqual(reloaded.get(b"job:job-1"), b'{"status":"completed"}')
            self.assertEqual(reloaded.lrange(b"processing_jobs", b"0", b"-1"), [])

    def test_update_claim_is_token_checked_and_replayed_from_aof(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            server = self.make_server(tmpdir)
            server.lpush(b"jobs", b"job-1")
            server.claim(
                b"jobs",
                b"processing_jobs",
                b"worker-1",
                b"claim-1",
                b"2026-01-01T00:00:00+00:00",
                b"60",
            )

            self.assertEqual(
                server.update_claim(
                    b"job-1",
                    b"job:job-1",
                    b'{"status":"running"}',
                    b"claim-1",
                ),
                1,
            )

            reloaded = self.make_server(tmpdir)
            self.assertEqual(reloaded.get(b"job:job-1"), b'{"status":"running"}')

    def test_finish_can_atomically_move_terminal_failure_to_dead_queue(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            server = self.make_server(tmpdir)
            server.lpush(b"jobs", b"job-1")
            server.claim(
                b"jobs",
                b"processing_jobs",
                b"worker-1",
                b"claim-1",
                b"2026-01-01T00:00:00+00:00",
                b"60",
            )

            self.assertEqual(
                server.finish(
                    b"processing_jobs",
                    b"dead_jobs",
                    b"job-1",
                    b"job:job-1",
                    b'{"status":"failed"}',
                    b"claim-1",
                ),
                1,
            )
            self.assertEqual(server.lrange(b"dead_jobs", b"0", b"-1"), [b"job-1"])

    def test_claim_requeue_and_ack_are_replayed_from_aof(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            server = self.make_server(tmpdir)
            server.lpush(b"jobs", b"job-1")
            server.claim(
                b"jobs",
                b"processing_jobs",
                b"worker-1",
                b"claim-1",
                b"2026-01-01T00:00:00+00:00",
                b"60",
            )
            server.requeue(
                b"processing_jobs",
                b"jobs",
                b"job-1",
                b"job:job-1",
                b'{"status":"queued"}',
                b"claim-1",
            )
            server.claim(
                b"jobs",
                b"processing_jobs",
                b"worker-2",
                b"claim-2",
                b"2026-01-01T00:01:00+00:00",
                b"60",
            )
            server.ack(b"processing_jobs", b"job-1", b"claim-2")

            reloaded = self.make_server(tmpdir)

            self.assertEqual(reloaded.lrange(b"jobs", b"0", b"-1"), [])
            self.assertEqual(reloaded.lrange(b"processing_jobs", b"0", b"-1"), [])
            self.assertIsNone(reloaded.get(b"worker_claim:job-1"))


if __name__ == "__main__":
    unittest.main()
