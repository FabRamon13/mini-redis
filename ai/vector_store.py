from ai.similarity import cosine_similarity
import heapq

class VectorStore:
    def __init__(self, entries=None):
        self.entries = entries or []

    def filter_entries(self, provider, model_id, model_revision, embedding_dimensions):
        return [
            entry
            for entry in self.entries
            if entry.get("provider") == provider
            and entry.get("model_id") == model_id
            and entry.get("model_revision") == model_revision
            and entry.get("embedding_dimensions") == embedding_dimensions
        ]

    def find_best_match(self, embedding, provider, model_id, model_revision, threshold):
        matches = self.search_top_k(
            embedding=embedding,
            provider=provider,
            model_id=model_id,
            model_revision=model_revision,
            k=1,
        )

        if not matches:
            return None, 0.0

        best = matches[0]

        if best["similarity_score"] >= threshold:
            return best["entry"], best["similarity_score"]

        return None, best["similarity_score"]

    def search_top_k(self, embedding, provider, model_id, model_revision, k=3):
        if isinstance(k, bool) or not isinstance(k, int) or k <= 0:
            raise ValueError("k must be a positive integer")

        candidates = self.filter_entries(
            provider=provider,
            model_id=model_id,
            model_revision=model_revision,
            embedding_dimensions=len(embedding),
        )
        scored = []

        for entry in candidates:
            score = cosine_similarity(
                embedding,
                entry["embedding"],
            )

            scored.append({
                "entry": entry,
                "similarity_score": score,
            })


        return heapq.nlargest(
            k,
            scored,
            key=lambda item: item["similarity_score"],
        )
