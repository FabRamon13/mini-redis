import time
import requests


BASE_URL = "http://127.0.0.1:8000"
USER_ID = "1"


def request_user():
    start = time.perf_counter()
    response = requests.get(f"{BASE_URL}/users/{USER_ID}")
    response.raise_for_status()
    latency_ms = (time.perf_counter() - start) * 1000
    return latency_ms, response.json()


def main():
    requests.delete(f"{BASE_URL}/cache/users/{USER_ID}")

    miss_latency, miss_response = request_user()
    hit_latency, hit_response = request_user()

    improvement = ((miss_latency - hit_latency) / miss_latency) * 100

    print("Cache miss latency:", round(miss_latency, 2), "ms")
    print("Cache hit latency:", round(hit_latency, 2), "ms")
    print("Latency improvement:", round(improvement, 2), "%")
    print("Miss source:", miss_response["source"])
    print("Hit source:", hit_response["source"])


if __name__ == "__main__":
    main()