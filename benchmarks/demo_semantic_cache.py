import argparse
import json
import statistics
import time
import urllib.error
import urllib.request
from dataclasses import dataclass


TERMINAL_STATUSES = {"completed", "failed", "dead"}
METRIC_KEYS = (
    "processed_jobs",
    "semantic_cache_hits",
    "semantic_cache_misses",
    "provider_call_count",
    "faiss_search_count",
    "failed_jobs",
    "dead_jobs",
)


@dataclass(frozen=True)
class DemoCase:
    phase: str
    prompt: str
    expected_cache: str


TOPIC_CLUSTERS = (
    (
        "what is redis",
        (
            "explain redis",
            "what is redis used for",
            "describe how redis stores data",
        ),
    ),
    (
        "what is faiss",
        (
            "explain faiss vector search",
            "what is faiss used for",
            "describe how faiss finds similar vectors",
        ),
    ),
    (
        "what is semantic caching",
        (
            "explain semantic cache",
            "why use a semantic cache",
            "describe caching based on meaning",
        ),
    ),
    (
        "what is vector search",
        (
            "explain vector similarity search",
            "what is nearest neighbor search",
            "describe searching with embeddings",
        ),
    ),
    (
        "what is a message queue",
        (
            "explain worker queues",
            "how do background job queues work",
            "describe asynchronous job processing",
        ),
    ),
    (
        "what is append only persistence",
        (
            "explain append only files",
            "how does an AOF restore data",
            "describe append only logging",
        ),
    ),
)

NEGATIVE_CONTROLS = (
    "how does photosynthesis work",
    "explain fixed rate mortgage interest",
    "what causes ocean tides",
    "describe how vaccines train the immune system",
)


def build_workload():
    seeds = [
        DemoCase("cold_seed", seed, "miss")
        for seed, _ in TOPIC_CLUSTERS
    ]
    semantic = [
        DemoCase("semantic", paraphrase, "hit")
        for _, paraphrases in TOPIC_CLUSTERS
        for paraphrase in paraphrases
    ]
    exact = [
        DemoCase("exact_repeat", seed, "hit")
        for seed, _ in TOPIC_CLUSTERS
        for _ in range(2)
    ]
    negative = [
        DemoCase("negative_control", prompt, "miss")
        for prompt in NEGATIVE_CONTROLS
    ]
    burst = [
        DemoCase("queue_burst", seed, "hit")
        for seed, _ in TOPIC_CLUSTERS
    ]
    return seeds + semantic + exact + negative, burst


class ApiClient:
    def __init__(self, base_url, timeout_seconds):
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def request_json(self, path, method="GET", payload=None):
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            self.base_url + path,
            data=body,
            method=method,
            headers={"Content-Type": "application/json"},
        )

        try:
            with urllib.request.urlopen(
                request,
                timeout=self.timeout_seconds,
            ) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"{method} {path} failed with HTTP {exc.code}: {detail}"
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"{method} {path} failed: {exc.reason}") from exc

    def submit(self, case, provider):
        started_at = time.perf_counter()
        response = self.request_json(
            "/inference",
            method="POST",
            payload={"prompt": case.prompt, "provider": provider},
        )
        return response["job_id"], started_at

    def get_job(self, job_id):
        return self.request_json(f"/jobs/{job_id}")

    def get_metrics(self):
        return self.request_json("/jobs/metrics")


def percentile(values, percentile_value):
    if not values:
        return 0.0

    ordered = sorted(values)
    rank = (len(ordered) - 1) * percentile_value
    lower_index = int(rank)
    upper_index = min(lower_index + 1, len(ordered) - 1)
    fraction = rank - lower_index
    return ordered[lower_index] + (
        ordered[upper_index] - ordered[lower_index]
    ) * fraction


def wait_for_job(client, job_id, started_at, poll_seconds, deadline):
    while time.monotonic() < deadline:
        job = client.get_job(job_id)
        status = job.get("status")

        if status in TERMINAL_STATUSES:
            latency_ms = (time.perf_counter() - started_at) * 1_000
            return job, latency_ms

        time.sleep(poll_seconds)

    raise TimeoutError(f"Timed out waiting for job {job_id}")


def result_record(case, job, latency_ms):
    status = job.get("status")
    result = job.get("result") or {}
    cache_status = result.get("cache", "unknown")

    return {
        "phase": case.phase,
        "prompt": case.prompt,
        "expected_cache": case.expected_cache,
        "status": status,
        "cache": cache_status,
        "matched_prompt": result.get("matched_prompt"),
        "similarity_score": result.get("similarity_score"),
        "latency_ms": latency_ms,
        "correct": (
            status == "completed"
            and cache_status == case.expected_cache
        ),
        "error": job.get("error"),
    }


def print_record(index, total, record):
    score = record["similarity_score"]
    score_text = f"{score:.4f}" if isinstance(score, (int, float)) else "n/a"
    matched = record["matched_prompt"] or "-"
    outcome = "PASS" if record["correct"] else "CHECK"

    print(
        f"{index:02}/{total} {outcome:<5} "
        f"phase={record['phase']:<16} "
        f"expected={record['expected_cache']:<4} "
        f"actual={record['cache']:<7} "
        f"score={score_text:<6} "
        f"latency={record['latency_ms']:8.2f}ms"
    )
    print(f"   query={record['prompt']!r}")
    if record["cache"] == "hit":
        print(f"   matched={matched!r}")
    if record["error"]:
        print(f"   error={record['error']}")


def run_sequential_cases(
    client,
    cases,
    provider,
    poll_seconds,
    job_timeout_seconds,
    start_index,
    total,
):
    records = []

    for offset, case in enumerate(cases):
        job_id, started_at = client.submit(case, provider)
        job, latency_ms = wait_for_job(
            client,
            job_id,
            started_at,
            poll_seconds,
            time.monotonic() + job_timeout_seconds,
        )
        record = result_record(case, job, latency_ms)
        records.append(record)
        print_record(start_index + offset, total, record)

    return records


def run_burst_cases(
    client,
    cases,
    provider,
    poll_seconds,
    job_timeout_seconds,
    start_index,
    total,
):
    pending = {}

    for case in cases:
        job_id, started_at = client.submit(case, provider)
        pending[job_id] = (case, started_at)

    deadline = time.monotonic() + job_timeout_seconds
    records = []

    while pending and time.monotonic() < deadline:
        for job_id in list(pending):
            job = client.get_job(job_id)
            if job.get("status") not in TERMINAL_STATUSES:
                continue

            case, started_at = pending.pop(job_id)
            record = result_record(
                case,
                job,
                (time.perf_counter() - started_at) * 1_000,
            )
            records.append(record)
            print_record(start_index + len(records) - 1, total, record)

        if pending:
            time.sleep(poll_seconds)

    if pending:
        raise TimeoutError(
            f"Timed out waiting for burst jobs: {', '.join(pending)}"
        )

    return records


def summarize_latency(records, cache_status):
    values = [
        record["latency_ms"]
        for record in records
        if record["status"] == "completed"
        and record["cache"] == cache_status
    ]

    if not values:
        return None

    return {
        "count": len(values),
        "avg": statistics.mean(values),
        "p50": statistics.median(values),
        "p95": percentile(values, 0.95),
    }


def metric_delta(before, after, key):
    return after.get(key, 0) - before.get(key, 0)


def print_summary(records, before, after):
    completed = [record for record in records if record["status"] == "completed"]
    failed = [record for record in records if record["status"] != "completed"]
    hits = [record for record in completed if record["cache"] == "hit"]
    misses = [record for record in completed if record["cache"] == "miss"]
    false_positives = [
        record
        for record in records
        if record["phase"] == "negative_control"
        and record["cache"] == "hit"
    ]
    semantic_misses = [
        record
        for record in records
        if record["phase"] == "semantic" and record["cache"] != "hit"
    ]
    exact_misses = [
        record
        for record in records
        if record["phase"] in {"exact_repeat", "queue_burst"}
        and record["cache"] != "hit"
    ]
    hit_latency = summarize_latency(records, "hit")
    miss_latency = summarize_latency(records, "miss")

    print("\nPortfolio Demo Summary")
    print("======================")
    print(f"Requests:              {len(records)}")
    print(f"Completed:             {len(completed)}")
    print(f"Failed/dead:           {len(failed)}")
    print(f"Cache hits:            {len(hits)}")
    print(f"Cache misses:          {len(misses)}")
    hit_rate = len(hits) / len(completed) * 100 if completed else 0
    print(f"Observed hit rate:     {hit_rate:.1f}%")
    print(f"False positives:       {len(false_positives)}")
    print(f"Semantic misses:       {len(semantic_misses)}")
    print(f"Exact-repeat misses:   {len(exact_misses)}")

    print("\nLatency (submission to completion)")
    print("----------------------------------")
    for label, summary in (("Hit", hit_latency), ("Miss", miss_latency)):
        if summary is None:
            print(f"{label:<5} no observations")
            continue
        print(
            f"{label:<5} n={summary['count']:<2} "
            f"avg={summary['avg']:.2f}ms "
            f"p50={summary['p50']:.2f}ms "
            f"p95={summary['p95']:.2f}ms"
        )

    if hit_latency and miss_latency:
        avoided_ms = max(
            0.0,
            (miss_latency["avg"] - hit_latency["avg"]) * len(hits),
        )
        print(f"Estimated E2E latency avoided: {avoided_ms / 1_000:.2f}s")

    print("\nMetric deltas")
    print("-------------")
    for key in METRIC_KEYS:
        print(f"{key:<24} {metric_delta(before, after, key):+}")

    print("\nFinal dashboard metrics")
    print("-----------------------")
    print(json.dumps(after, indent=2, sort_keys=True))

    if false_positives:
        print("\nNegative controls that incorrectly hit")
        print("--------------------------------------")
        for record in false_positives:
            print(
                f"{record['prompt']!r} -> "
                f"{record['matched_prompt']!r} "
                f"(score={record['similarity_score']})"
            )

    if semantic_misses:
        print("\nSemantic paraphrases that missed")
        print("--------------------------------")
        for record in semantic_misses:
            print(
                f"{record['phase']}: {record['prompt']!r} "
                f"(best score={record['similarity_score']})"
            )

    if exact_misses:
        print("\nExact repeats that unexpectedly missed")
        print("--------------------------------------")
        for record in exact_misses:
            print(f"{record['phase']}: {record['prompt']!r}")

    return not failed and not false_positives and not exact_misses


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Run a phased semantic-cache workload and print a "
            "portfolio-friendly correctness and latency report."
        )
    )
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8000",
        help="FastAPI base URL (default: %(default)s)",
    )
    parser.add_argument(
        "--provider",
        default="huggingface",
        choices=("fake", "huggingface"),
    )
    parser.add_argument("--poll-seconds", type=float, default=0.25)
    parser.add_argument("--job-timeout-seconds", type=float, default=120.0)
    parser.add_argument("--http-timeout-seconds", type=float, default=30.0)
    parser.add_argument(
        "--skip-burst",
        action="store_true",
        help="Skip the final six-job queue burst.",
    )
    return parser.parse_args()


def validate_args(args):
    for name in (
        "poll_seconds",
        "job_timeout_seconds",
        "http_timeout_seconds",
    ):
        if getattr(args, name) <= 0:
            raise ValueError(f"--{name.replace('_', '-')} must be positive")


def main():
    args = parse_args()
    validate_args(args)
    client = ApiClient(args.base_url, args.http_timeout_seconds)
    sequential, burst = build_workload()
    if args.skip_burst:
        burst = []

    total = len(sequential) + len(burst)
    before = client.get_metrics()

    print("Semantic Cache Portfolio Demo")
    print("=============================")
    print(f"API:      {args.base_url}")
    print(f"Provider: {args.provider}")
    print(f"Requests: {total}")
    print(
        "Phases:   cold seeds -> semantic paraphrases -> "
        "exact repeats -> negative controls -> queue burst"
    )
    print()

    records = run_sequential_cases(
        client,
        sequential,
        args.provider,
        args.poll_seconds,
        args.job_timeout_seconds,
        start_index=1,
        total=total,
    )

    if burst:
        print("\nSubmitting final queue burst...")
        records.extend(
            run_burst_cases(
                client,
                burst,
                args.provider,
                args.poll_seconds,
                args.job_timeout_seconds,
                start_index=len(records) + 1,
                total=total,
            )
        )

    after = client.get_metrics()
    healthy = print_summary(records, before, after)
    if not healthy:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
