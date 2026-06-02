import argparse
import random
import statistics
import sys
import time
from pathlib import Path

import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ai.faiss_store import FaissVectorStore
from ai.vector_store import VectorStore


MODEL_ID = "sentence-transformers/all-MiniLM-L6-v2"
MODEL_REVISION = "main"
PROVIDER = "huggingface"
DEFAULT_SIZES = (100, 1_000, 10_000)


def random_vector(rng, dimensions):
    return [rng.random() for _ in range(dimensions)]


def make_entries(rng, size, dimensions):
    return [
        {
            "entry_id": str(index),
            "prompt": f"prompt-{index}",
            "provider": PROVIDER,
            "model_id": MODEL_ID,
            "model_revision": MODEL_REVISION,
            "embedding_dimensions": dimensions,
            "embedding": random_vector(rng, dimensions),
            "response": {"message": f"response-{index}"},
            "created_at": "benchmark",
        }
        for index in range(size)
    ]


def percentile(values, percentile_value):
    ordered = sorted(values)
    rank = (len(ordered) - 1) * percentile_value
    lower_index = int(rank)
    upper_index = min(lower_index + 1, len(ordered) - 1)
    fraction = rank - lower_index
    return ordered[lower_index] + (ordered[upper_index] - ordered[lower_index]) * fraction


def benchmark_search(search, iterations, warmups):
    for _ in range(warmups):
        search()

    latencies_ms = []

    for _ in range(iterations):
        started_at = time.perf_counter()
        search()
        latencies_ms.append((time.perf_counter() - started_at) * 1_000)

    return latencies_ms


def benchmark_linear(entries, query, k, iterations, warmups):
    store = VectorStore(entries)
    latencies_ms = benchmark_search(
        search=lambda: store.search_top_k(
            embedding=query,
            provider=PROVIDER,
            model_id=MODEL_ID,
            model_revision=MODEL_REVISION,
            k=k,
        ),
        iterations=iterations,
        warmups=warmups,
    )
    return latencies_ms


def benchmark_faiss(entries, query, dimensions, k, iterations, warmups):
    store = FaissVectorStore(dimensions)
    vectors = np.asarray(
        [entry["embedding"] for entry in entries],
        dtype="float32",
    )
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)

    if np.any(norms == 0):
        raise ValueError("zero vector is not allowed")

    build_started_at = time.perf_counter()
    store.index.add(vectors / norms)
    store.entries.extend(entries)
    build_ms = (time.perf_counter() - build_started_at) * 1_000
    latencies_ms = benchmark_search(
        search=lambda: store.search_top_k(
            embedding=query,
            k=k,
        ),
        iterations=iterations,
        warmups=warmups,
    )
    return build_ms, latencies_ms


def summarize(label, latencies_ms):
    return {
        "engine": label,
        "avg_ms": statistics.fmean(latencies_ms),
        "p50_ms": percentile(latencies_ms, 0.50),
        "p95_ms": percentile(latencies_ms, 0.95),
    }


def print_result(size, k, build_ms, linear, faiss):
    improvement = linear["avg_ms"] / faiss["avg_ms"]
    print()
    print(f"Vectors: {size}")
    print(f"K: {k}")
    print(f"FAISS build time: {build_ms:.3f} ms")
    print(
        "Linear avg/p50/p95: "
        f"{linear['avg_ms']:.3f} / {linear['p50_ms']:.3f} / {linear['p95_ms']:.3f} ms"
    )
    print(
        "FAISS  avg/p50/p95: "
        f"{faiss['avg_ms']:.3f} / {faiss['p50_ms']:.3f} / {faiss['p95_ms']:.3f} ms"
    )
    print(f"Search speedup: {improvement:.2f}x")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Compare isolated FAISS and linear Top-K vector search latency.",
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
    print("FAISS vs Linear Vector Search Benchmark")
    print("--------------------------------------")

    for index, size in enumerate(args.sizes):
        rng = random.Random(args.seed + index)
        entries = make_entries(rng, size, args.dimensions)
        query = random_vector(rng, args.dimensions)
        linear_latencies_ms = benchmark_linear(
            entries=entries,
            query=query,
            k=args.k,
            iterations=args.iterations,
            warmups=args.warmups,
        )
        faiss_build_ms, faiss_latencies_ms = benchmark_faiss(
            entries=entries,
            query=query,
            dimensions=args.dimensions,
            k=args.k,
            iterations=args.iterations,
            warmups=args.warmups,
        )
        print_result(
            size=size,
            k=args.k,
            build_ms=faiss_build_ms,
            linear=summarize("linear", linear_latencies_ms),
            faiss=summarize("faiss", faiss_latencies_ms),
        )


if __name__ == "__main__":
    main()
