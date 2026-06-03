import socket
from redis_clone.exceptions import CommandError
from redis_clone.protocol import ProtocolHandler, Error
import threading

class Client:
    def __init__(self, host="127.0.0.1", port=31337):
        self._protocol = ProtocolHandler()
        self._lock = threading.RLock()

        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.connect((host, port))

        self._fh = self._socket.makefile("rwb")

    """
    sends out commands 
    """
    def execute(self, *args):
        with self._lock:
            self._protocol.write_response(self._fh, args)

            response = self._protocol.handle_request(self._fh)

            if isinstance(response, Error):
                raise CommandError(response.message)

            return response
    """
    method to close socket
    """
    def close(self):
        with self._lock:
            try:
                self._fh.close()
            finally:
                self._socket.close()

    def get(self, key):
        return self.execute("GET", key)

    def set(self, key, value, *options):
        return self.execute("SET", key, value, *options)

    def delete(self, key):
        return self.execute("DELETE", key)

    def flush(self):
        return self.execute("FLUSH")

    def mget(self, *keys):
        return self.execute("MGET", *keys)

    def mset(self, *items):
        return self.execute("MSET", *items)
    def ping(self):
        return self.execute("PING")
    
    def exists(self,key):
        return self.execute("EXISTS", key)
    def ttl(self,key):
        return self.execute("TTL",key)
    def lpush(self,key,*values):
        return self.execute("LPUSH", key, *values)
    def rpop(self, key):
        return self.execute("RPOP", key)

    def llen(self, key):
        return self.execute("LLEN", key)
    def incr(self,key):
        return self.execute("INCR", key)
    def lrange(self, key, start, stop):
        return self.execute("LRANGE", key, start, stop)
    def rpoplpush(self, source, destination):
        return self.execute("RPOPLPUSH", source, destination)
    def lrem(self, key, value):
        return self.execute("LREM", key, value)
    def claim(self, source, destination, worker_id, claim_token, claimed_at, lease_seconds):
        return self.execute(
            "CLAIM",
            source,
            destination,
            worker_id,
            claim_token,
            claimed_at,
            str(lease_seconds),
        )
    def requeue(self, source, destination, job_id, job_key, job_payload, claim_token):
        return self.execute(
            "REQUEUE",
            source,
            destination,
            job_id,
            job_key,
            job_payload,
            claim_token,
        )
    def ack(self, source, job_id, claim_token):
        return self.execute("ACK", source, job_id, claim_token)
    def finish(self, source, destination, job_id, job_key, job_payload, claim_token):
        return self.execute(
            "FINISH",
            source,
            destination,
            job_id,
            job_key,
            job_payload,
            claim_token,
        )
    def update_claim(self, job_id, job_key, job_payload, claim_token):
        return self.execute("UPDATECLAIM", job_id, job_key, job_payload, claim_token)
    def enqueue(self, queue_key, job_id, job_key, job_payload, max_size):
        return self.execute(
            "ENQUEUE",
            queue_key,
            job_id,
            job_key,
            job_payload,
            str(max_size),
        )
    def incrby(self, key, amount):
        return self.execute("INCRBY", key, str(amount))
