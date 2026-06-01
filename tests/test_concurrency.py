from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

from redis_clone.client import Client

def worker(i):
    client = Client()
    key = f"user:{i}"
    value = f"value:{i}"

    assert client.set(key,value) == 1
    assert client.get(key) == value.encode()

    return True 

def main():
    client = Client()
    client.flush()

    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(worker,range(50)))


    assert all(results)
    print("Concurrent client test passed.")


if __name__ == "__main__":
    main()

