from client import Client
import time 


client = Client()

import time
from client import Client

client = Client()

print("Resetting database...")
client.flush()

print("Testing EXISTS...")
assert client.exists("missing") == 0

client.set("name", "Ramon")
assert client.exists("name") == 1

client.delete("name")
assert client.exists("name") == 0

print("Testing TTL for missing key...")
assert client.ttl("missing") == -2

print("Testing TTL for key without expiration...")
client.set("permanent", "value")
assert client.ttl("permanent") == -1

print("Testing TTL for expiring key...")
client.set("temp", "123", "EX", "2")

ttl_value = client.ttl("temp")
assert ttl_value in (1, 2)

assert client.exists("temp") == 1
assert client.get("temp") == b"123"

time.sleep(3)

assert client.get("temp") is None
assert client.exists("temp") == 0
assert client.ttl("temp") == -2

print("All EXISTS and TTL tests passed.")

print("Testing PING...")
assert client.ping() == b"PONG"

print("Testing SET/GET...")
assert client.set("name", "Ramon") == 1
assert client.get("name") == b"Ramon"

print("Testing overwrite...")
client.set("name", "John")
assert client.get("name") == b"John"

print("Testing missing key...")
assert client.get("missing") is None

print("Testing MSET/MGET...")
assert client.mset("k1", "v1", "k2", "v2") == 2
assert client.mget("k1", "k2") == [b"v1", b"v2"]

print("Testing DELETE...")
assert client.delete("k1") == 1
assert client.get("k1") is None
assert client.delete("k1") == 0

print("Testing FLUSH...")
client.set("a", "1")
client.set("b", "2")
assert client.flush() >= 2

print("Testing TTL expiration...")
client.set("temp", "123", "EX", "2")
assert client.get("temp") == b"123"
time.sleep(3)
assert client.get("temp") is None

print("All tests passed.")