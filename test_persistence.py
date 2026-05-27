import sys
from client import Client

client = Client()
key = "persistent_name"

if len(sys.argv) > 1 and sys.argv[1] == "write":
    print("Writing persistent value...")
    client.flush()
    assert client.set(key, "Ramon") == 1
    assert client.get(key) == b"Ramon"
    print("Now restart the server and run: python test_persistence.py read")

elif len(sys.argv) > 1 and sys.argv[1] == "read":
    print("Reading persistent value after restart...")
    assert client.get(key) == b"Ramon"
    print("Persistence test passed.")

else:
    print("Usage:")
    print("python test_persistence.py write")
    print("restart server")
    print("python test_persistence.py read")