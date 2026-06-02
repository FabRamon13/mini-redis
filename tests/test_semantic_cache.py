import json
import unittest
import uuid
from unittest.mock import patch

from worker.worker import load_non_negative_float
from worker.worker import load_semantic_cache_threshold
from worker.worker import process_inference
from worker.faiss_index import get_faiss_index
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


if __name__ == "__main__":
    unittest.main()
