import unittest

from worker.faiss_index import add_to_faiss
from worker.faiss_index import get_faiss_index
from worker.faiss_index import rebuild_faiss_indexes
from worker.faiss_index import reset_faiss_indexes


class FaissIndexTests(unittest.TestCase):
    def setUp(self):
        reset_faiss_indexes()

    def tearDown(self):
        reset_faiss_indexes()

    def make_entry(
        self,
        entry_id,
        embedding,
        provider="huggingface",
        model_id="sentence-transformers/all-MiniLM-L6-v2",
        model_revision="main",
    ):
        return {
            "entry_id": entry_id,
            "prompt": f"prompt-{entry_id}",
            "provider": provider,
            "model_id": model_id,
            "model_revision": model_revision,
            "embedding_dimensions": len(embedding),
            "embedding": embedding,
            "response": {"answer": entry_id},
            "created_at": "test",
        }

    def get_index(self, entries):
        return get_faiss_index(
            entries=entries,
            provider="huggingface",
            model_id="sentence-transformers/all-MiniLM-L6-v2",
            model_revision="main",
            dimensions=2,
        )

    def test_rebuild_filters_incompatible_entries(self):
        valid = self.make_entry("valid", [1.0, 0.0])
        wrong_provider = self.make_entry("wrong-provider", [1.0, 0.0], provider="fake")
        wrong_revision = self.make_entry("wrong-revision", [1.0, 0.0], model_revision="old")
        wrong_dimensions = self.make_entry("wrong-dimensions", [1.0, 0.0, 0.0])

        store = self.get_index([
            valid,
            wrong_provider,
            wrong_revision,
            wrong_dimensions,
        ])

        self.assertEqual(store.index.ntotal, 1)
        self.assertEqual(store.entries, [valid])

    def test_add_to_faiss_updates_existing_compatible_index(self):
        first = self.make_entry("first", [1.0, 0.0])
        second = self.make_entry("second", [0.0, 1.0])
        store = self.get_index([first])

        self.assertTrue(add_to_faiss(second))
        self.assertFalse(add_to_faiss(second))
        self.assertEqual(store.index.ntotal, 2)

    def test_get_faiss_index_rebuilds_after_redis_projection_changes(self):
        first = self.make_entry("first", [1.0, 0.0])
        second = self.make_entry("second", [0.0, 1.0])
        first_store = self.get_index([first])
        second_store = self.get_index([second])

        self.assertIsNot(second_store, first_store)
        self.assertEqual(second_store.entries, [second])

    def test_rebuild_faiss_indexes_builds_each_huggingface_signature(self):
        current = self.make_entry("current", [1.0, 0.0])
        old = self.make_entry("old", [0.0, 1.0], model_revision="old")
        fake = self.make_entry("fake", [1.0, 0.0], provider="fake")

        count = rebuild_faiss_indexes([current, old, fake], provider="huggingface")

        self.assertEqual(count, 2)

    def test_rebuild_skips_invalid_zero_vector_without_crashing(self):
        valid = self.make_entry("valid", [1.0, 0.0])
        zero = self.make_entry("zero", [0.0, 0.0])

        store = self.get_index([valid, zero])

        self.assertEqual(store.entries, [valid])


if __name__ == "__main__":
    unittest.main()
