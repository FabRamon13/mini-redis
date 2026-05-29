import time
import statistics
import requests

URL = "http://127.0.0.1:8000/users/1"

def request_once():
    start = time.perf_counter()
    response = requests.get(URL)
    response.raise_for_status()
    return (time.perf_counter() - start) * 1000

def main():
    latencies = [request_once() for _ in range(20)]
    print("Requests:", len(latencies))
    print("p50 latency:", round(statistics.median(latencies), 2), "ms")
    print("p95 latency:", round(sorted(latencies)[int(len(latencies) * 0.95) - 1], 2), "ms")
    print("avg latency:", round(statistics.mean(latencies), 2), "ms")

if __name__ == "__main__":
    main()