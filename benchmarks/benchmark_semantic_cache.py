import time
import statistics 
import requests 

BASE_URL = "http://127.0.0.1:8000"
PROMPT= "what is a cache"
REQUESTS = 10

def submit_inference(prompt):
    response = requests.post(
        f"{BASE_URL}/inference",
        json={"prompt": prompt},
        timeout=10,
    )
    response.raise_for_status()
    return response.json()["job_id"]


def wait_for_job(job_id):
    start = time.perf_counter()

    while True:
        response = requests.get(
            f"{BASE_URL}/jobs/{job_id}",
            timeout=10,
        )
        response.raise_for_status()

        job = response.json()

        if job["status"] in ("completed", "failed"):
            latency_ms = (time.perf_counter() - start) * 1000
            return job, latency_ms

        time.sleep(0.05)


def percentile(values, pct):
    sorted_values = sorted(values)
    index = int(len(sorted_values) * pct) - 1
    index = max(index, 0)
    return sorted_values[index]


def main():
    latencies = []
    hits = 0
    misses = 0

    for i in range(REQUESTS):
        job_id = submit_inference(PROMPT)
        job, latency_ms = wait_for_job(job_id)

        if job["status"] == "failed":
            print("Job failed:", job)
            continue

        result = job["result"]
        cache_status = result["cache"]

        if cache_status == "hit":
            hits += 1
        else:
            misses += 1

        latencies.append(latency_ms)

        print(
            f"Request {i + 1}: cache={cache_status}, "
            f"latency={round(latency_ms, 2)}ms"
        )

    total = hits + misses
    hit_rate = hits / total if total else 0

    print("\nSemantic Cache Benchmark")
    print("------------------------")
    print("Requests:", total)
    print("Hits:", hits)
    print("Misses:", misses)
    print("Hit rate:", round(hit_rate, 4))
    print("p50 latency:", round(statistics.median(latencies), 2), "ms")
    print("p95 latency:", round(percentile(latencies, 0.95), 2), "ms")
    print("avg latency:", round(statistics.mean(latencies), 2), "ms")


if __name__ == "__main__":
    main()