import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ai.faiss_store import FaissVectorStore


def main():
    store = FaissVectorStore(dimensions=3)

    store.add({
        "entry_id": "a",
        "prompt": "cache",
        "embedding": [1.0, 0.0, 0.0],
    })

    store.add({
        "entry_id": "b",
        "prompt": "database",
        "embedding": [0.0, 1.0, 0.0],
    })

    results = store.search_top_k(
        embedding=[0.9, 0.1, 0.0],
        k=2,
    )

    for result in results:
        print(
            result["entry"]["prompt"],
            round(result["similarity_score"], 4),
        )


if __name__ == "__main__":
    main()
