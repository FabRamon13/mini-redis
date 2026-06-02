import unittest

from ai.vector_store import VectorStore


class VectorStoreTests(unittest.TestCase):
    def make_entry(
        self,
        prompt,
        embedding,
        provider="fake",
        model_id="hash-embedding-v1",
        model_revision="v1",
    ):
        return {
            "prompt": prompt,
            "provider": provider,
            "model_id": model_id,
            "model_revision": model_revision,
            "embedding": embedding,
            "embedding_dimensions": len(embedding),
            "response": {"answer": prompt},
        }

    def test_search_top_k_returns_highest_scores_first(self):
        store = VectorStore([
            self.make_entry("exact", [1.0, 0.0]),
            self.make_entry("partial", [0.8, 0.2]),
            self.make_entry("different", [0.0, 1.0]),
        ])

        matches = store.search_top_k(
            embedding=[1.0, 0.0],
            provider="fake",
            model_id="hash-embedding-v1",
            model_revision="v1",
            k=2,
        )

        self.assertEqual(
            [match["entry"]["prompt"] for match in matches],
            ["exact", "partial"],
        )

    def test_search_top_k_filters_incompatible_entries(self):
        store = VectorStore([
            self.make_entry("valid", [1.0, 0.0]),
            self.make_entry("wrong-provider", [1.0, 0.0], provider="huggingface"),
            self.make_entry("wrong-model", [1.0, 0.0], model_id="hash-embedding-v0"),
            self.make_entry("wrong-revision", [1.0, 0.0], model_revision="v0"),
            self.make_entry("wrong-dimensions", [1.0, 0.0, 0.0]),
        ])

        matches = store.search_top_k(
            embedding=[1.0, 0.0],
            provider="fake",
            model_id="hash-embedding-v1",
            model_revision="v1",
        )

        self.assertEqual(
            [match["entry"]["prompt"] for match in matches],
            ["valid"],
        )

    def test_find_best_match_applies_threshold(self):
        store = VectorStore([
            self.make_entry("partial", [0.8, 0.2]),
        ])

        match, score = store.find_best_match(
            embedding=[1.0, 0.0],
            provider="fake",
            model_id="hash-embedding-v1",
            model_revision="v1",
            threshold=1.0,
        )

        self.assertIsNone(match)
        self.assertGreater(score, 0.0)


if __name__ == "__main__":
    unittest.main()
