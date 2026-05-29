from gevent.pool import Pool
from gevent.server import StreamServer
import time, os
from threading import Lock, RLock
from exceptions import CommandError, Disconnect
from protocol import ProtocolHandler, Error

    


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
        }
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

        
        with self._lock:
            # Mutating operations are synchronized to maintain consistency
            # across concurrent client requests.

            self._kv[key] = value

            if options:
                if len(options) != 2:
                    raise CommandError("SET options must be EX seconds")
                
                option, seconds = options

                if option.upper() != b"EX":
                    raise CommandError("Only EX option is supported")

                self._expiry[key] = time.time() + float(seconds)

            else:
                self._expiry.pop(key, None)
            
            #Persist the mutation for crash recovery
            self._append_to_aof([b"SET", key, value] + list(options))

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

    def flush(self):
        with self._lock:
            self._append_to_aof([b"FLUSH"])
            kvlen = len(self._kv)
            self._kv.clear()
            self._expiry.clear()
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
            return queue.pop()
    
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
                    except Disconnect:
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
