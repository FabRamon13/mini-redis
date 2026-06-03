import unittest

from worker.faiss_index import add_to_faiss
from worker.faiss_index import get_faiss_index_size
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

    def test_rebuild_builds_one_index_for_one_signature(self):
        first = self.make_entry("first", [1.0, 0.0])
        second = self.make_entry("second", [0.0, 1.0])

        count = rebuild_faiss_indexes([first, second])

        self.assertEqual(count, 1)
        self.assertEqual(get_faiss_index_size(), 2)

    def test_rebuild_builds_multiple_indexes_for_multiple_signatures(self):
        current = self.make_entry("current", [1.0, 0.0])
        old_revision = self.make_entry("old-revision", [0.0, 1.0], model_revision="old")
        other_model = self.make_entry("other-model", [1.0, 0.0], model_id="other-model")
        other_dimensions = self.make_entry("other-dimensions", [1.0, 0.0, 0.0])

        count = rebuild_faiss_indexes([
            current,
            old_revision,
            other_model,
            other_dimensions,
        ])

        self.assertEqual(count, 4)
        self.assertEqual(get_faiss_index_size(), 4)

    def test_rebuild_provider_filter_only_builds_matching_provider(self):
        huggingface = self.make_entry("huggingface", [1.0, 0.0])
        fake = self.make_entry("fake", [1.0, 0.0], provider="fake")

        count = rebuild_faiss_indexes([huggingface, fake], provider="huggingface")

        self.assertEqual(count, 1)
        self.assertEqual(get_faiss_index_size(), 1)
        self.assertEqual(
            self.get_index([huggingface, fake]).entries,
            [huggingface],
        )

    def test_search_returns_nearest_match_after_rebuild(self):
        cache = self.make_entry("cache", [1.0, 0.0])
        database = self.make_entry("database", [0.0, 1.0])

        rebuild_faiss_indexes([cache, database], provider="huggingface")
        store = self.get_index([cache, database])
        results = store.search_top_k([0.9, 0.1], k=2)

        self.assertEqual(
            [result["entry"]["entry_id"] for result in results],
            ["cache", "database"],
        )

    def test_rebuild_ignores_malformed_signature_entries(self):
        valid = self.make_entry("valid", [1.0, 0.0])
        missing_provider = dict(valid, entry_id="missing-provider", provider="")
        missing_model = dict(valid, entry_id="missing-model", model_id="")
        missing_revision = dict(valid, entry_id="missing-revision", model_revision="")
        missing_dimensions = dict(valid, entry_id="missing-dimensions", embedding_dimensions=0)
        negative_dimensions = dict(
            valid,
            entry_id="negative-dimensions",
            embedding_dimensions=-1,
        )
        string_dimensions = dict(
            valid,
            entry_id="string-dimensions",
            embedding_dimensions="2",
        )
        bool_dimensions = dict(
            valid,
            entry_id="bool-dimensions",
            embedding_dimensions=True,
        )

        count = rebuild_faiss_indexes([
            valid,
            missing_provider,
            missing_model,
            missing_revision,
            missing_dimensions,
            negative_dimensions,
            string_dimensions,
            bool_dimensions,
        ])

        self.assertEqual(count, 1)
        self.assertEqual(get_faiss_index_size(), 1)

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

    def test_get_faiss_index_size_returns_zero_when_empty(self):
        self.assertEqual(get_faiss_index_size(), 0)

    def test_get_faiss_index_size_counts_single_index_vectors(self):
        first = self.make_entry("first", [1.0, 0.0])
        second = self.make_entry("second", [0.0, 1.0])

        self.get_index([first, second])

        self.assertEqual(get_faiss_index_size(), 2)

    def test_get_faiss_index_size_sums_multiple_indexes(self):
        current = self.make_entry("current", [1.0, 0.0])
        old = self.make_entry("old", [0.0, 1.0], model_revision="old")

        rebuild_faiss_indexes([current, old], provider="huggingface")

        self.assertEqual(get_faiss_index_size(), 2)

    def test_get_faiss_index_size_can_filter_by_signature(self):
        current = self.make_entry("current", [1.0, 0.0])
        old = self.make_entry("old", [0.0, 1.0], model_revision="old")

        rebuild_faiss_indexes([current, old], provider="huggingface")

        self.assertEqual(
            get_faiss_index_size(
                provider="huggingface",
                model_id="sentence-transformers/all-MiniLM-L6-v2",
                model_revision="main",
                dimensions=2,
            ),
            1,
        )
        self.assertEqual(
            get_faiss_index_size(
                provider="huggingface",
                model_id="sentence-transformers/all-MiniLM-L6-v2",
                model_revision="missing",
                dimensions=2,
            ),
            0,
        )

    def test_get_faiss_index_size_ignores_duplicate_add(self):
        first = self.make_entry("first", [1.0, 0.0])
        self.get_index([first])

        add_to_faiss(first)

        self.assertEqual(get_faiss_index_size(), 1)

    def test_get_faiss_index_size_resets_to_zero(self):
        first = self.make_entry("first", [1.0, 0.0])
        self.get_index([first])

        reset_faiss_indexes()

        self.assertEqual(get_faiss_index_size(), 0)


if __name__ == "__main__":
    unittest.main()
