import json
import unittest
import uuid
from unittest.mock import ANY, Mock
from unittest.mock import patch

from worker.worker import load_non_negative_float
from worker.worker import load_semantic_cache_threshold
from worker.worker import load_vector_search_engine
from worker.worker import process_inference
from worker.worker import rebuild_worker_faiss_indexes
from worker.faiss_index import get_faiss_index
from worker.faiss_index import get_faiss_index_size
from worker.faiss_index import reset_faiss_indexes
from worker.semantic_cache import get_model_id
from worker.semantic_cache import get_semantic_cache_entries
from worker.semantic_cache import prune_semantic_cache
from worker.semantic_cache import save_semantic_cache_entry


class MemoryClient:
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

    def incrby(self, key, amount):
        value = int(self.data.get(key, "0")) + int(amount)
        self.data[key] = str(value)
        return value

    def delete(self, key):
        return int(self.data.pop(key, None) is not None)

    def lpush(self, key, *values):
        items = self.lists.setdefault(key, [])

        for value in values:
            items.insert(0, value)

        return len(items)

    def lrange(self, key, start, stop):
        items = self.lists.get(key, [])

        if stop == -1:
            stop = len(items) - 1

        return items[start:stop + 1]

    def lrem(self, key, value):
        items = self.lists.get(key, [])
        remaining = [item for item in items if item != value]
        removed = len(items) - len(remaining)
        self.lists[key] = remaining
        return removed


class WorkerFaissStartupTests(unittest.TestCase):
    def setUp(self):
        reset_faiss_indexes()

    def tearDown(self):
        reset_faiss_indexes()

    def make_entry(self, entry_id, embedding):
        return {
            "entry_id": entry_id,
            "prompt": f"prompt-{entry_id}",
            "provider": "huggingface",
            "model_id": "sentence-transformers/all-MiniLM-L6-v2",
            "model_revision": "main",
            "embedding_dimensions": len(embedding),
            "embedding": embedding,
            "response": {"answer": entry_id},
            "created_at": "test",
        }

    @patch("worker.worker.get_semantic_cache_entries")
    def test_worker_startup_rebuilds_faiss_from_semantic_cache_entries(self, mock_entries):
        mock_client = Mock()
        entries = [
            self.make_entry("first", [1.0, 0.0]),
            self.make_entry("second", [0.0, 1.0]),
        ]
        mock_entries.return_value = entries

        with patch("worker.worker.VECTOR_SEARCH_ENGINE", "faiss"):
            count = rebuild_worker_faiss_indexes(mock_client)

        mock_entries.assert_called_once_with(mock_client)
        self.assertEqual(count, 1)
        self.assertEqual(get_faiss_index_size(), 2)

        store = get_faiss_index(
            entries=entries,
            provider="huggingface",
            model_id="sentence-transformers/all-MiniLM-L6-v2",
            model_revision="main",
            dimensions=2,
        )
        results = store.search_top_k([0.9, 0.1], k=1)

        self.assertEqual(results[0]["entry"]["entry_id"], "first")


class SemanticCacheTests(unittest.TestCase):
    def test_demo_delay_accepts_non_negative_number(self):
        with patch.dict("os.environ", {"DEMO_DELAY": "1.5"}):
            self.assertEqual(load_non_negative_float("DEMO_DELAY", 0.0), 1.5)

    def test_demo_delay_rejects_invalid_values(self):
        for value in ("invalid", "-0.1", "nan", "inf"):
            with self.subTest(value=value):
                with patch.dict("os.environ", {"DEMO_DELAY": value}):
                    with self.assertRaises(ValueError):
                        load_non_negative_float("DEMO_DELAY", 0.0)

    def test_semantic_cache_threshold_defaults_to_point_seven_five(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(load_semantic_cache_threshold(), 0.75)

    def test_semantic_cache_threshold_accepts_valid_override(self):
        self.assertEqual(load_semantic_cache_threshold("0.9"), 0.9)

    def test_semantic_cache_threshold_rejects_invalid_values(self):
        for value in ("invalid", "-0.1", "1.1", "nan", "inf"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                        load_semantic_cache_threshold(value)

    def test_vector_search_engine_defaults_to_faiss(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(load_vector_search_engine(), "faiss")

    def test_vector_search_engine_accepts_supported_values_case_insensitively(self):
        self.assertEqual(load_vector_search_engine("linear"), "linear")
        self.assertEqual(load_vector_search_engine("FAISS"), "faiss")

    def test_vector_search_engine_rejects_invalid_value(self):
        with self.assertRaises(ValueError):
            load_vector_search_engine("vector_store")

    def test_save_semantic_cache_entry_uses_valid_uuid_and_metadata(self):
        client = MemoryClient()
        embedding = [0.1, 0.2, 0.3]

        saved_entry = save_semantic_cache_entry(
            client,
            "what is a cache",
            embedding,
            {"answer": "cached response"},
            "fake",
        )
        entry_id = saved_entry["entry_id"]

        self.assertEqual(str(uuid.UUID(entry_id)), entry_id)

        cache_key = f"semantic_cache:{entry_id}"
        entry = json.loads(client.data[cache_key])

        self.assertEqual(entry["entry_id"], entry_id)
        self.assertEqual(entry["prompt"], "what is a cache")
        self.assertEqual(entry["provider"], "fake")
        self.assertEqual(entry["model_id"], "hash-embedding-v1")
        self.assertEqual(entry["model_revision"], "v1")
        self.assertEqual(entry["embedding"], embedding)
        self.assertEqual(entry["response"], {"answer": "cached response"})
        self.assertEqual(entry["embedding_dimensions"], 3)
        self.assertIn("created_at", entry)

    def test_save_semantic_cache_entry_creates_distinct_indexed_entries(self):
        client = MemoryClient()

        first_entry = save_semantic_cache_entry(
            client,
            "first prompt",
            [1.0, 0.0],
            {"answer": "first"},
            "fake",
        )
        second_entry = save_semantic_cache_entry(
            client,
            "second prompt",
            [0.0, 1.0],
            {"answer": "second"},
            "fake",
        )
        first_id = first_entry["entry_id"]
        second_id = second_entry["entry_id"]

        self.assertNotEqual(first_id, second_id)

        index = client.lrange("semantic_cache:index", 0, -1)
        self.assertEqual(
            index,
            [
                f"semantic_cache:{second_id}",
                f"semantic_cache:{first_id}",
            ],
        )

        entries = get_semantic_cache_entries(client)
        self.assertEqual([entry["entry_id"] for entry in entries], [second_id, first_id])

    def test_save_semantic_cache_entry_skips_equivalent_duplicate(self):
        client = MemoryClient()

        first_entry = save_semantic_cache_entry(
            client,
            "same prompt",
            [1.0, 0.0],
            {"answer": "first"},
            "fake",
            max_entries=10,
        )
        second_entry = save_semantic_cache_entry(
            client,
            "same prompt",
            [1.0, 0.0],
            {"answer": "second"},
            "fake",
            max_entries=10,
        )
        first_id = first_entry["entry_id"]
        second_id = second_entry["entry_id"]

        self.assertEqual(second_id, first_id)
        self.assertEqual(
            client.lrange("semantic_cache:index", 0, -1),
            [f"semantic_cache:{first_id}"],
        )

    def test_save_semantic_cache_entry_prunes_oldest_entries(self):
        client = MemoryClient()

        first_entry = save_semantic_cache_entry(
            client,
            "first prompt",
            [1.0, 0.0],
            {"answer": "first"},
            "fake",
            max_entries=2,
        )
        second_entry = save_semantic_cache_entry(
            client,
            "second prompt",
            [0.0, 1.0],
            {"answer": "second"},
            "fake",
            max_entries=2,
        )
        third_entry = save_semantic_cache_entry(
            client,
            "third prompt",
            [0.5, 0.5],
            {"answer": "third"},
            "fake",
            max_entries=2,
        )
        first_id = first_entry["entry_id"]
        second_id = second_entry["entry_id"]
        third_id = third_entry["entry_id"]

        self.assertNotIn(f"semantic_cache:{first_id}", client.data)
        self.assertEqual(
            client.lrange("semantic_cache:index", 0, -1),
            [
                f"semantic_cache:{third_id}",
                f"semantic_cache:{second_id}",
            ],
        )

    def test_semantic_cache_limit_rejects_invalid_boundaries(self):
        client = MemoryClient()

        for max_entries in (True, 0, -1, 1.5, "10"):
            with self.subTest(max_entries=max_entries):
                with self.assertRaises(ValueError):
                    prune_semantic_cache(client, max_entries)

    def test_model_ids_are_stable_for_supported_providers(self):
        self.assertEqual(get_model_id("fake"), "hash-embedding-v1")
        self.assertEqual(
            get_model_id("huggingface"),
            "sentence-transformers/all-MiniLM-L6-v2",
        )
        self.assertEqual(get_model_id("unsupported"), "unknown")

    def test_process_inference_skips_entry_with_incompatible_dimensions(self):
        client = MemoryClient()
        save_semantic_cache_entry(
            client,
            "cached prompt",
            [1.0, 0.0, 0.0],
            {"answer": "stale"},
            "fake",
        )

        with (
            patch("worker.worker.get_embedding", return_value=[1.0, 0.0]),
            patch("worker.worker.generate_response", return_value={"answer": "fresh"}),
            patch("worker.worker.time.sleep"),
        ):
            result = process_inference({"prompt": "new prompt", "provider": "fake"}, client)

        self.assertEqual(result["cache"], "miss")
        self.assertEqual(result["response"], {"answer": "fresh"})

    def test_process_inference_skips_entry_from_different_model(self):
        client = MemoryClient()
        saved_entry = save_semantic_cache_entry(
            client,
            "cached prompt",
            [1.0, 0.0],
            {"answer": "stale"},
            "fake",
        )
        entry_id = saved_entry["entry_id"]
        cache_key = f"semantic_cache:{entry_id}"
        entry = json.loads(client.data[cache_key])
        entry["model_id"] = "hash-embedding-v0"
        client.data[cache_key] = json.dumps(entry)

        with (
            patch("worker.worker.get_embedding", return_value=[1.0, 0.0]),
            patch("worker.worker.generate_response", return_value={"answer": "fresh"}),
            patch("worker.worker.time.sleep"),
        ):
            result = process_inference({"prompt": "new prompt", "provider": "fake"}, client)

        self.assertEqual(result["cache"], "miss")
        self.assertEqual(result["response"], {"answer": "fresh"})

    def test_process_inference_uses_configured_threshold(self):
        client = MemoryClient()
        save_semantic_cache_entry(
            client,
            "cached prompt",
            [0.8, 0.2],
            {"answer": "cached"},
            "fake",
        )

        with (
            patch("worker.worker.get_embedding", return_value=[1.0, 0.0]),
            patch("worker.worker.SEMANTIC_CACHE_THRESHOLD", 1.0),
            patch("worker.worker.generate_response", return_value={"answer": "fresh"}),
            patch("worker.worker.time.sleep"),
        ):
            result = process_inference({"prompt": "new prompt", "provider": "fake"}, client)

        self.assertEqual(result["cache"], "miss")
        self.assertEqual(result["response"], {"answer": "fresh"})

    def test_process_inference_hit_includes_formatted_top_matches(self):
        client = MemoryClient()
        saved_entry = save_semantic_cache_entry(
            client,
            "cached prompt",
            [1.0, 0.0],
            {"answer": "cached"},
            "fake",
        )
        entry_id = saved_entry["entry_id"]

        with patch("worker.worker.get_embedding", return_value=[1.0, 0.0]):
            result = process_inference({"prompt": "new prompt", "provider": "fake"}, client)

        self.assertEqual(result["cache"], "hit")
        self.assertNotIn("metrics:provider_call_count", client.data)
        self.assertNotIn("metrics:provider_latency_ms_total", client.data)
        self.assertEqual(
            result["top_matches"],
            [{
                "entry_id": entry_id,
                "prompt": "cached prompt",
                "provider": "fake",
                "model_id": "hash-embedding-v1",
                "model_revision": "v1",
                "similarity_score": 1.0,
            }],
        )

    def test_process_inference_miss_includes_below_threshold_top_matches(self):
        client = MemoryClient()
        saved_entry = save_semantic_cache_entry(
            client,
            "different prompt",
            [0.0, 1.0],
            {"answer": "cached"},
            "fake",
        )
        entry_id = saved_entry["entry_id"]

        with (
            patch("worker.worker.get_embedding", return_value=[1.0, 0.0]),
            patch("worker.worker.generate_response", return_value={"answer": "fresh"}),
            patch("worker.worker.time.sleep"),
        ):
            result = process_inference({"prompt": "new prompt", "provider": "fake"}, client)

        self.assertEqual(result["cache"], "miss")
        self.assertEqual(
            result["top_matches"],
            [{
                "entry_id": entry_id,
                "prompt": "different prompt",
                "provider": "fake",
                "model_id": "hash-embedding-v1",
                "model_revision": "v1",
                "similarity_score": 0.0,
            }],
        )

    def test_process_inference_empty_cache_includes_empty_top_matches(self):
        client = MemoryClient()

        with (
            patch("worker.worker.get_embedding", return_value=[1.0, 0.0]),
            patch("worker.worker.generate_response", return_value={"answer": "fresh"}),
            patch("worker.worker.time.sleep"),
        ):
            result = process_inference({"prompt": "new prompt", "provider": "fake"}, client)

        self.assertEqual(result["cache"], "miss")
        self.assertEqual(result["top_matches"], [])

    def test_huggingface_miss_adds_saved_entry_to_local_faiss_index(self):
        client = MemoryClient()
        reset_faiss_indexes()

        with (
            patch("worker.worker.get_embedding", return_value=[1.0, 0.0]),
            patch("worker.worker.generate_response", return_value={"answer": "fresh"}),
            patch("worker.worker.time.sleep"),
        ):
            result = process_inference(
                {"prompt": "new prompt", "provider": "huggingface"},
                client,
            )

        entries = get_semantic_cache_entries(client)
        store = get_faiss_index(
            entries=entries,
            provider="huggingface",
            model_id="sentence-transformers/all-MiniLM-L6-v2",
            model_revision="main",
            dimensions=2,
        )
        matches = store.search_top_k([1.0, 0.0], k=1)

        self.assertEqual(result["cache"], "miss")
        self.assertEqual(store.index.ntotal, 1)
        self.assertEqual(matches[0]["entry"]["prompt"], "new prompt")
        self.assertEqual(client.data["metrics:faiss_search_count"], "1")

    def test_huggingface_search_uses_faiss_engine_when_configured(self):
        client = MemoryClient()
        faiss_store = Mock()
        faiss_store.search_top_k.return_value = []

        with (
            patch("worker.worker.VECTOR_SEARCH_ENGINE", "faiss"),
            patch("worker.worker.get_embedding", return_value=[1.0, 0.0]),
            patch("worker.worker.generate_response", return_value={"answer": "fresh"}),
            patch("worker.worker.get_faiss_index", return_value=faiss_store) as get_index,
            patch("worker.worker.add_to_faiss") as add_entry,
            patch("worker.worker.time.perf_counter", side_effect=[1.0, 1.0005, 2.0, 2.25]),
            patch("worker.worker.time.sleep"),
            patch("worker.worker.log_event") as log_event,
        ):
            process_inference({"prompt": "new prompt", "provider": "huggingface"}, client)

        get_index.assert_called_once()
        faiss_store.search_top_k.assert_called_once_with(
            embedding=[1.0, 0.0],
            k=3,
        )
        add_entry.assert_called_once()
        log_event.assert_any_call(
            ANY,
            "vector_search_started",
            request_id=None,
            job_id=None,
            provider="huggingface",
            search_engine="faiss",
            candidate_count=0,
        )
        log_event.assert_any_call(
            ANY,
            "vector_search_completed",
            request_id=None,
            job_id=None,
            provider="huggingface",
            search_engine="faiss",
            candidate_count=0,
            result_count=0,
            duration_ms=0.5,
        )
        self.assertEqual(client.data["metrics:faiss_search_count"], "1")
        self.assertEqual(client.data["metrics:faiss_search_latency_us_total"], "500")
        self.assertEqual(client.data["metrics:provider_call_count"], "1")
        self.assertEqual(client.data["metrics:provider_latency_ms_total"], "250")

    def test_huggingface_search_uses_linear_fallback_when_configured(self):
        client = MemoryClient()

        with (
            patch("worker.worker.VECTOR_SEARCH_ENGINE", "linear"),
            patch("worker.worker.get_embedding", return_value=[1.0, 0.0]),
            patch("worker.worker.generate_response", return_value={"answer": "fresh"}),
            patch("worker.worker.get_faiss_index") as get_index,
            patch("worker.worker.add_to_faiss") as add_entry,
            patch("worker.worker.time.perf_counter", side_effect=[1.0, 1.125, 2.0, 2.25]),
            patch("worker.worker.time.sleep"),
            patch("worker.worker.log_event") as log_event,
        ):
            result = process_inference(
                {"prompt": "new prompt", "provider": "huggingface"},
                client,
            )

        self.assertEqual(result["cache"], "miss")
        get_index.assert_not_called()
        add_entry.assert_not_called()
        log_event.assert_any_call(
            ANY,
            "vector_search_started",
            request_id=None,
            job_id=None,
            provider="huggingface",
            search_engine="linear",
            candidate_count=0,
        )
        log_event.assert_any_call(
            ANY,
            "vector_search_completed",
            request_id=None,
            job_id=None,
            provider="huggingface",
            search_engine="linear",
            candidate_count=0,
            result_count=0,
            duration_ms=125,
        )
        self.assertEqual(client.data["metrics:linear_search_count"], "1")
        self.assertEqual(client.data["metrics:linear_search_latency_us_total"], "125000")
        self.assertEqual(client.data["metrics:provider_call_count"], "1")
        self.assertEqual(client.data["metrics:provider_latency_ms_total"], "250")

    def test_fake_provider_logs_effective_linear_engine(self):
        client = MemoryClient()

        with (
            patch("worker.worker.VECTOR_SEARCH_ENGINE", "faiss"),
            patch("worker.worker.get_embedding", return_value=[1.0, 0.0]),
            patch("worker.worker.generate_response", return_value={"answer": "fresh"}),
            patch("worker.worker.time.perf_counter", side_effect=[1.0, 1.125, 2.0, 2.25]),
            patch("worker.worker.time.sleep"),
            patch("worker.worker.log_event") as log_event,
        ):
            process_inference({"prompt": "new prompt", "provider": "fake"}, client)

        log_event.assert_any_call(
            ANY,
            "vector_search_started",
            request_id=None,
            job_id=None,
            provider="fake",
            search_engine="linear",
            candidate_count=0,
        )
        log_event.assert_any_call(
            ANY,
            "vector_search_completed",
            request_id=None,
            job_id=None,
            provider="fake",
            search_engine="linear",
            candidate_count=0,
            result_count=0,
            duration_ms=125,
        )
        self.assertEqual(client.data["metrics:linear_search_count"], "1")
        self.assertEqual(client.data["metrics:linear_search_latency_us_total"], "125000")
        self.assertEqual(client.data["metrics:provider_call_count"], "1")
        self.assertEqual(client.data["metrics:provider_latency_ms_total"], "250")

    def test_linear_engine_skips_worker_startup_faiss_rebuild(self):
        client = MemoryClient()

        with (
            patch("worker.worker.VECTOR_SEARCH_ENGINE", "linear"),
            patch("worker.worker.rebuild_faiss_indexes") as rebuild_indexes,
        ):
            rebuilt = rebuild_worker_faiss_indexes(client)

        self.assertEqual(rebuilt, 0)
        rebuild_indexes.assert_not_called()


if __name__ == "__main__":
    unittest.main()
