import numpy as np
import faiss


class FaissVectorStore:
    def __init__(self, dimensions: int):
        if isinstance(dimensions, bool) or not isinstance(dimensions, int) or dimensions <= 0:
            raise ValueError("dimensions must be a positive integer")

        self.dimensions = dimensions
        self.index = faiss.IndexFlatIP(dimensions)
        self.entries = []

    def _normalize(self, vector):
        array = np.array(vector, dtype="float32")

        if array.shape != (self.dimensions,):
            raise ValueError("vector has incorrect dimensions")

        norm = np.linalg.norm(array)

        if norm == 0:
            raise ValueError("zero vector is not allowed")

        return array / norm

    def add(self, entry):
        vector = self._normalize(entry["embedding"])

        self.index.add(
            np.array([vector], dtype="float32")
        )

        self.entries.append(entry)

    def search_top_k(self, embedding, k=3):
        if isinstance(k, bool) or not isinstance(k, int) or k <= 0:
            raise ValueError("k must be a positive integer")

        if self.index.ntotal == 0:
            return []

        query = self._normalize(embedding)

        scores, indices = self.index.search(
            np.array([query], dtype="float32"),
            min(k, self.index.ntotal),
        )

        results = []

        for score, index in zip(scores[0], indices[0]):
            if index == -1:
                continue

            results.append({
                "entry": self.entries[index],
                "similarity_score": float(score),
            })

        return results
