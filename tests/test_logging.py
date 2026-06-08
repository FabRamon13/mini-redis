import io
import json
import logging
import unittest

from observability.logging import JsonFormatter, log_event


class JsonLoggingTests(unittest.TestCase):
    def make_logger(self):
        stream = io.StringIO()
        logger = logging.getLogger(f"test-json-logger-{id(stream)}")
        logger.handlers = []
        logger.propagate = False
        logger.setLevel(logging.INFO)

        handler = logging.StreamHandler(stream)
        handler.setFormatter(JsonFormatter("test-service"))
        logger.addHandler(handler)

        return logger, stream

    def test_log_event_emits_parseable_json_with_context(self):
        logger, stream = self.make_logger()

        log_event(
            logger,
            "job_finished",
            request_id="request-1",
            job_id="job-1",
            worker_id="worker-1",
            duration_ms=12.5,
        )

        payload = json.loads(stream.getvalue())

        self.assertEqual(payload["service"], "test-service")
        self.assertEqual(payload["level"], "info")
        self.assertEqual(payload["event"], "job_finished")
        self.assertEqual(payload["request_id"], "request-1")
        self.assertEqual(payload["job_id"], "job-1")
        self.assertEqual(payload["worker_id"], "worker-1")
        self.assertEqual(payload["duration_ms"], 12.5)
        self.assertTrue(payload["timestamp"].endswith("+00:00"))

    def test_log_event_redacts_sensitive_fields(self):
        logger, stream = self.make_logger()

        log_event(
            logger,
            "job_claimed",
            job_id="job-1",
            worker_id="worker-1",
            lease_seconds=60,
            claim_token="secret-token",
            prompt="private prompt",
            embedding=[1.0, 0.0],
            response={"private": True},
        )

        payload = json.loads(stream.getvalue())

        self.assertNotIn("claim_token", payload)
        self.assertNotIn("prompt", payload)
        self.assertNotIn("embedding", payload)
        self.assertNotIn("response", payload)
