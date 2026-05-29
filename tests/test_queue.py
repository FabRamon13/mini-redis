import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from client import Client


client = Client()

print("Testing queue commands...")
client.flush()

assert client.llen("jobs") == 0

assert client.lpush("jobs", "job1") == 1
assert client.lpush("jobs", "job2") == 2

assert client.llen("jobs") == 2

assert client.rpop("jobs") == b"job1"
assert client.rpop("jobs") == b"job2"
assert client.rpop("jobs") is None

print("Queue tests passed.")