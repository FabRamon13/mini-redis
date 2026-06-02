from gevent.pool import Pool
from gevent.server import StreamServer
import json
import math
import time, os
from threading import RLock
from redis_clone.exceptions import CommandError, Disconnect
from redis_clone.protocol import ProtocolHandler, Error

    


class Server:
    """
    TCP server, implements:

    RESP command parsing
    concurrent client handling
    in memory data storage
    TTL expiration
    Append only file persistence
    """
    def __init__(self, host="127.0.0.1", port=31337, max_clients=64, aof_file="appendonly.aof"):
        #protects shared state across concurrent clients 
        self._lock = RLock()

        #limits # of active client connected simultaneously
        self._pool = Pool(max_clients)

        #TCP server responsible for accepting connections 
        ##dispatches requests to connection handler 
        self._server = StreamServer(
            (host, port),
            self.connection_handler,
            spawn=self._pool,
        )

        self._protocol = ProtocolHandler()

        ##primary in memory k/v store
        self._kv = {}

        ##tracks key expiration timestamps
        self._expiry = {}

        #redis style list storage for queue operations
        self._lists = {}

        self._commands = self.get_commands()

        #prevents AOF writes while replaying persistent data
        self._loading = False

        self._aof_file = aof_file

        #restore state from AOF log
        self.load_persistence()


    
    def connection_handler(self, conn, address):
        """
        Process commands over a persistent client connection until
        the client disconnects

        """
        socket_file = conn.makefile("rwb")

        while True:
            try:
                data = self._protocol.handle_request(socket_file)
            except Disconnect:
                break

            try:
                response = self.get_response(data)
            except CommandError as exc:
                response = Error(exc.args[0])

            self._protocol.write_response(socket_file, response)

    def get_response(self, data):
        """
        Validate incoming requests and dispatch them to the
        appropriate command handler.
        """
        if not isinstance(data, list):
            try:
                data = data.split()
            except Exception:
                raise CommandError("Request must be list or simple string.")

        if not data:
            raise CommandError("Missing command")

        command = data[0].upper()

        if command not in self._commands:
            raise CommandError(f"Unrecognized command: {command!r}")

        ##where the actual command execution happens
        return self._commands[command](*data[1:])
        
    def get_commands(self):
        return {
            b"GET": self.get,
            b"SET": self.set,
            b"DELETE": self.delete,
            b"FLUSH": self.flush,
            b"MGET": self.mget,
            b"MSET": self.mset,
            b"PING": self.ping,
            b"EXISTS": self.exists,
            b"TTL": self.ttl,
            b"LPUSH": self.lpush,
            b"RPOP": self.rpop,
            b"LLEN": self.llen,
            b"INCR": self.incr,
            b"LRANGE": self.lrange,
            b"RPOPLPUSH": self.rpoplpush,
            b"LREM": self.lrem,
            b"CLAIM": self.claim,
            b"REQUEUE": self.requeue,
            b"ACK": self.ack,
            b"UPDATECLAIM": self.update_claim,
            b"FINISH": self.finish,
            b"ENQUEUE": self.enqueue,
            b"EXPIREAT": self.expireat,
        }
    def incr(self, *args):
        self._require_args("INCR", args, 1)
        key = args[0]

        with self._lock:
            if self._is_expired(key):
                current = None
            else:
                current = self._kv.get(key)

            if current is None:
                value = 1
            else:
                try:
                    value = int(current) + 1
                except (TypeError, ValueError):
                    raise CommandError("value is not an integer")

            self._kv[key] = str(value).encode("utf-8")
            self._append_to_aof([b"INCR", key])

            return value
    def get(self, *args):
        self._require_args("GET", args,1)

        key = args[0]
        
        with self._lock:

            if self._is_expired(key):
                return None
            
            return self._kv.get(key)

    def set(self, *args):
        self._require_min_args("SET", args, 2)

        key = args[0]
        value = args[1]
        options = args[2:]
        expiry = None

        if options:
            if len(options) != 2:
                raise CommandError("SET options must be EX seconds")

            option, seconds = options

            if option.upper() != b"EX":
                raise CommandError("Only EX option is supported")

            try:
                ttl_seconds = float(seconds)
            except (TypeError, ValueError):
                raise CommandError("invalid expire time")

            if ttl_seconds <= 0:
                raise CommandError("invalid expire time")

            expiry = time.time() + ttl_seconds

        with self._lock:
            self._kv[key] = value

            if expiry is None:
                self._expiry.pop(key, None)
            else:
                self._expiry[key] = expiry

            self._append_to_aof([b"SET", key, value])

            if expiry is not None:
                self._append_to_aof([
                    b"EXPIREAT",
                    key,
                    str(expiry).encode("utf-8"),
                ])

        return 1

    def delete(self, *args):
        self._require_args("DELETE", args, 1)
        key = args[0]
        
        with self._lock:
            if self._is_expired(key):
                return 0
            if key in self._kv:
                del self._kv[key]
                self._expiry.pop(key, None)
                self._append_to_aof([b"DELETE", key])
                return 1
            
        return 0

    def flush(self, *args):
        self._require_args("FLUSH", args, 0)

        with self._lock:
            kvlen = len(self._kv)
            self._kv.clear()
            self._expiry.clear()
            self._lists.clear()

            self._append_to_aof([b"FLUSH"])

        return kvlen

    def mget(self, *keys):
        with self._lock:
            self._require_min_args("MGET", keys, 1)
            return [self.get(key) for key in keys]

    def mset(self, *items):
        self._require_min_args("MSET",items,2)

        if len(items) %2 != 0:
            raise CommandError("MSET requires k/v pairs")
        
        data = list(zip(items[::2], items[1::2]))
        with self._lock:
            for k,v in data:
                self._kv[k] = v
                self._expiry.pop(k, None)

            self._append_to_aof([b"MSET"] + list(items))
            
            return len(data)

    def rpoplpush(self, *args):
        self._require_args("RPOPLPUSH", args, 2)

        source = args[0]
        destination = args[1]

        with self._lock:
            source_values = self._lists.get(source)

            if not source_values:
                return None

            value = source_values.pop()

            self._lists.setdefault(destination, [])
            self._lists[destination].insert(0, value)

            self._append_to_aof([b"RPOPLPUSH", source, destination])

            return value

    def lrem(self, *args):
        self._require_args("LREM", args, 2)

        key = args[0]
        value = args[1]

        with self._lock:
            values = self._lists.get(key, [])
            new_values = [item for item in values if item != value]
            removed = len(values) - len(new_values)

            if removed:
                self._lists[key] = new_values
                self._append_to_aof([b"LREM", key, value])

            return removed

    def claim(self, *args):
        self._require_args("CLAIM", args, 6)

        source, destination, worker_id, claim_token, claimed_at, raw_lease_seconds = args

        try:
            lease_seconds = int(raw_lease_seconds)
        except (TypeError, ValueError):
            raise CommandError("invalid lease seconds")

        if lease_seconds <= 0:
            raise CommandError("invalid lease seconds")

        try:
            claim_payload = json.dumps({
                "worker_id": worker_id.decode("utf-8"),
                "claim_token": claim_token.decode("utf-8"),
                "claimed_at": claimed_at.decode("utf-8"),
                "lease_seconds": lease_seconds,
            }).encode("utf-8")
        except (AttributeError, UnicodeDecodeError):
            raise CommandError("invalid claim metadata")

        with self._lock:
            source_values = self._lists.get(source)

            if not source_values:
                return None

            job_id = source_values.pop()
            self._lists.setdefault(destination, []).insert(0, job_id)
            self._kv[self._claim_key(job_id)] = claim_payload

            self._append_to_aof([
                b"CLAIM",
                source,
                destination,
                worker_id,
                claim_token,
                claimed_at,
                str(lease_seconds).encode("utf-8"),
            ])

            return job_id

    def requeue(self, *args):
        self._require_args("REQUEUE", args, 6)

        source, destination, job_id, job_key, job_payload, claim_token = args

        with self._lock:
            if not self._claim_token_matches(job_id, claim_token):
                return 0

            source_values = self._lists.get(source, [])
            remaining_values = [item for item in source_values if item != job_id]
            removed = len(source_values) - len(remaining_values)

            if not removed:
                return 0

            self._lists[source] = remaining_values
            destination_values = self._lists.setdefault(destination, [])

            if job_id not in destination_values:
                destination_values.insert(0, job_id)

            self._kv[job_key] = job_payload
            self._expiry.pop(job_key, None)
            self._kv.pop(self._claim_key(job_id), None)

            self._append_to_aof([
                b"REQUEUE",
                source,
                destination,
                job_id,
                job_key,
                job_payload,
                claim_token,
            ])

            return removed

    def ack(self, *args):
        self._require_args("ACK", args, 3)

        source, job_id, claim_token = args

        with self._lock:
            if not self._claim_token_matches(job_id, claim_token):
                return 0

            source_values = self._lists.get(source, [])
            remaining_values = [item for item in source_values if item != job_id]
            removed = len(source_values) - len(remaining_values)
            claim_key = self._claim_key(job_id)
            claim_removed = self._kv.pop(claim_key, None) is not None
            self._expiry.pop(claim_key, None)

            if removed:
                self._lists[source] = remaining_values

            if removed or claim_removed:
                self._append_to_aof([b"ACK", source, job_id, claim_token])

            return removed

    def finish(self, *args):
        self._require_args("FINISH", args, 6)

        source, destination, job_id, job_key, job_payload, claim_token = args

        with self._lock:
            if not self._claim_token_matches(job_id, claim_token):
                return 0

            source_values = self._lists.get(source, [])
            remaining_values = [item for item in source_values if item != job_id]
            removed = len(source_values) - len(remaining_values)

            if not removed:
                return 0

            self._lists[source] = remaining_values

            if destination:
                destination_values = self._lists.setdefault(destination, [])

                if job_id not in destination_values:
                    destination_values.insert(0, job_id)

            self._kv[job_key] = job_payload
            self._expiry.pop(job_key, None)
            self._kv.pop(self._claim_key(job_id), None)

            self._append_to_aof([
                b"FINISH",
                source,
                destination,
                job_id,
                job_key,
                job_payload,
                claim_token,
            ])

            return removed

    def update_claim(self, *args):
        self._require_args("UPDATECLAIM", args, 4)

        job_id, job_key, job_payload, claim_token = args

        with self._lock:
            if not self._claim_token_matches(job_id, claim_token):
                return 0

            self._kv[job_key] = job_payload
            self._expiry.pop(job_key, None)
            self._append_to_aof([b"UPDATECLAIM", job_id, job_key, job_payload, claim_token])

            return 1
    
    def ping(self):
        return b"PONG"

    def exists(self,*args):
        self._require_args("EXISTS", args, 1)
        key = args[0]

        with self._lock:
            if self._is_expired(key):
                return 0 
            return 1 if key in self._kv else 0
    
    def ttl(self,*args):
        self._require_args("TTL", args,1)
        key = args[0]
        
        with self._lock:
            if self._is_expired(key):
                return -2 ##key doesnt exists 

            if key not in self._kv:
                return -2

            if key not in self._expiry:
                return -1

            return int(self._expiry[key] - time.time())
        
    def lpush(self, *args):
        """
        Insert one or more values at the head of list.

        Support Redis style queue and messaging workloads
        """

        self._require_min_args("LPUSH", args,2)

        key = args[0]
        values = args[1:]

        with self._lock:
            if key not in self._lists:
                #lazily initialize the list on first write
                self._lists[key] = []
            
            #insert at the head to preserve LPUSH 
            for value in values:
                self._lists[key].insert(0,value)

            self._append_to_aof([b"LPUSH", key] + list(values))

            return len(self._lists[key])
    
    def rpop(self, *args):
        """
        Remove and return the rightmost element of a list.

        When paired with LPUSH, provides FIFO queue behavior.
        """
        
        self._require_args("RPOP", args, 1)

        key = args[0]

        with self._lock:
            queue = self._lists.get(key)

            ##return nil for missing or empty list
            if not queue:
                return None
            
            #remove from the tail of the list
            value = queue.pop()
            self._append_to_aof([b"RPOP", key])

            return value
    
    def llen(self, *args):
        self._require_args("LLEN", args, 1)

        key = args[0]

        with self._lock:
            return len(self._lists.get(key, []))
        
    
    
    def _is_expired(self, key):
        """
        Implements lazy expiration

        Expired keys are removed when accessed.
        Currently avoids dedicated background cleanup processes
        """

        expires_at = self._expiry.get(key)

        if expires_at is None:
            return False

        if time.time() > expires_at:
            self._kv.pop(key, None)
            self._expiry.pop(key, None)
            return True
        
        return False

    def _claim_key(self, job_id):
        if isinstance(job_id, bytes):
            return b"worker_claim:" + job_id

        return f"worker_claim:{job_id}"

    def _claim_token_matches(self, job_id, claim_token):
        claim_payload = self._kv.get(self._claim_key(job_id))

        if claim_payload is None:
            return claim_token in (b"", "")

        try:
            claim = json.loads(claim_payload.decode("utf-8"))
            expected_token = claim["claim_token"]
            supplied_token = (
                claim_token.decode("utf-8")
                if isinstance(claim_token, bytes)
                else claim_token
            )
        except (AttributeError, KeyError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
            return False

        return supplied_token == expected_token
    
    """
    helper functions to help with command validation 
    """
    def _require_args(self,command, args,expected):
        if len(args) != expected:
            raise CommandError(f"{command} requires {expected} argument(s)")
        
    
    def _require_min_args(self, command, args, minimum):
        if len(args) < minimum:
            raise CommandError(f"{command} requires at least {minimum} argument(s)")

  
    def load_persistence(self):
        """
        Reconstruct in-memory state by replaying commands from
        the append-only log during server startup.
        """
        if not os.path.exists(self._aof_file):
            return
        

        # Disable persistence writes during replay to avoid
        # duplicating commands in the append-only log.
        self._loading = True

        try:
            with open(self._aof_file, "rb") as f:
                while True:
                    try:
                        data = self._protocol.handle_request(f)
                    except (CommandError, Disconnect):
                        break

                    self.get_response(data)
        finally:
            self._loading = False 


    
    def _append_to_aof(self, command_parts):
        """
        Persist mutating commands to the append-only log.

        The log is replayed during startup to restore durable state.
        """

        if self._loading:
            #skip writes while replaying persistence data
            return 
        
        with open(self._aof_file, "ab") as f:
            self._protocol.write_response(f, command_parts)

    def lrange(self, *args):
        self._require_args("LRANGE", args, 3)

        key = args[0]

        try:
            start = int(args[1])
            stop = int(args[2])
        except (TypeError, ValueError):
            raise CommandError("LRANGE start and stop must be integers")

        with self._lock:
            values = self._lists.get(key, [])
            length = len(values)

            if start < 0:
                start = max(length + start, 0)

            if stop < 0:
                stop = length + stop

            if start > stop or start >= length or stop < 0:
                return []

            return values[start:stop + 1]

    def enqueue(self, *args):
        self._require_args("ENQUEUE", args, 5)

        queue_key = args[0]
        job_id = args[1]
        job_key = args[2]
        job_payload = args[3]

        try:
            max_size = int(args[4])
        except (TypeError, ValueError):
            raise CommandError("invalid max queue size")

        if max_size <= 0:
            raise CommandError("invalid max queue size")

        with self._lock:
            queue = self._lists.setdefault(queue_key, [])

            if len(queue) >= max_size:
                raise CommandError("queue is full")

            self._kv[job_key] = job_payload
            self._expiry.pop(job_key, None)
            queue.insert(0, job_id)

            self._append_to_aof([
                b"ENQUEUE",
                queue_key,
                job_id,
                job_key,
                job_payload,
                str(max_size).encode("utf-8")
            ])

            return b"OK"
    def expireat(self, *args):
        self._require_args("EXPIREAT", args, 2)

        key = args[0]

        try:
            expire_at = float(args[1])
        except (TypeError, ValueError):
            raise CommandError("invalid expire timestamp")

        if not math.isfinite(expire_at):
            raise CommandError("invalid expire timestamp")

        with self._lock:
            if key not in self._kv:
                return 0

            if expire_at <= time.time():
                self._kv.pop(key, None)
                self._expiry.pop(key, None)
                return 0

            self._expiry[key] = expire_at
            self._append_to_aof([
                b"EXPIREAT",
                key,
                str(expire_at).encode("utf-8"),
            ])

            return 1
    
    def run(self):
        """
        start TCP server and begin accepting connections 
        """
        self._server.serve_forever()
 

if __name__ == "__main__":
    host = os.getenv("REDIS_BIND_HOST", "127.0.0.1")
    port = int(os.getenv("REDIS_PORT", "31337"))
    aof_file = os.getenv("AOF_FILE", "appendonly.aof")

    server = Server(host = host, port = port, aof_file = aof_file)
    server.run()
