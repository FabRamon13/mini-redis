import argparse
import random
import statistics
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ai.vector_store import VectorStore


MODEL_ID = "sentence-transformers/all-MiniLM-L6-v2"
MODEL_REVISION = "main"
PROVIDER = "huggingface"
DEFAULT_SIZES = (100, 1_000, 10_000)


def random_vector(rng, dimensions):
    return [rng.random() for _ in range(dimensions)]


def generate_entries(rng, count, dimensions):
    return [
        {
            "entry_id": str(index),
            "provider": PROVIDER,
            "model_id": MODEL_ID,
            "model_revision": MODEL_REVISION,
            "embedding_dimensions": dimensions,
            "embedding": random_vector(rng, dimensions),
            "prompt": f"prompt-{index}",
        }
        for index in range(count)
    ]


def percentile(values, percentile_value):
    ordered = sorted(values)
    rank = (len(ordered) - 1) * percentile_value
    lower_index = int(rank)
    upper_index = min(lower_index + 1, len(ordered) - 1)
    fraction = rank - lower_index
    return ordered[lower_index] + (ordered[upper_index] - ordered[lower_index]) * fraction


def benchmark_size(vector_count, dimensions, k, iterations, warmups, seed):
    rng = random.Random(seed)
    entries = generate_entries(rng, vector_count, dimensions)
    query_vector = random_vector(rng, dimensions)
    vector_store = VectorStore(entries)
    candidates = vector_store.filter_entries(
        provider=PROVIDER,
        model_id=MODEL_ID,
        model_revision=MODEL_REVISION,
        embedding_dimensions=dimensions,
    )

    search_kwargs = {
        "embedding": query_vector,
        "provider": PROVIDER,
        "model_id": MODEL_ID,
        "model_revision": MODEL_REVISION,
        "k": k,
    }

    for _ in range(warmups):
        vector_store.search_top_k(**search_kwargs)

    latencies_ms = []

    for _ in range(iterations):
        started_at = time.perf_counter()
        vector_store.search_top_k(**search_kwargs)
        latencies_ms.append((time.perf_counter() - started_at) * 1_000)

    return {
        "vectors": vector_count,
        "candidates": len(candidates),
        "k": k,
        "avg_ms": statistics.fmean(latencies_ms),
        "p50_ms": percentile(latencies_ms, 0.50),
        "p95_ms": percentile(latencies_ms, 0.95),
    }


def print_result(result):
    print("=================================")
    print(f"Vectors: {result['vectors']}")
    print(f"Candidates: {result['candidates']}")
    print(f"K: {result['k']}")
    print()
    print(f"avg: {result['avg_ms']:.3f} ms")
    print(f"p50: {result['p50_ms']:.3f} ms")
    print(f"p95: {result['p95_ms']:.3f} ms")
    print("=================================")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Benchmark isolated linear Top-K vector search latency.",
    )
    parser.add_argument("--sizes", nargs="+", type=int, default=DEFAULT_SIZES)
    parser.add_argument("--dimensions", type=int, default=384)
    parser.add_argument("--k", type=int, default=3)
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument("--warmups", type=int, default=3)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    if any(size <= 0 for size in args.sizes):
        parser.error("--sizes values must be positive")
    if args.dimensions <= 0:
        parser.error("--dimensions must be positive")
    if args.k <= 0:
        parser.error("--k must be positive")
    if args.iterations <= 0:
        parser.error("--iterations must be positive")
    if args.warmups < 0:
        parser.error("--warmups must be non-negative")

    return args


def main():
    args = parse_args()

    for index, vector_count in enumerate(args.sizes):
        result = benchmark_size(
            vector_count=vector_count,
            dimensions=args.dimensions,
            k=args.k,
            iterations=args.iterations,
            warmups=args.warmups,
            seed=args.seed + index,
        )
        print_result(result)


if __name__ == "__main__":
    main()
