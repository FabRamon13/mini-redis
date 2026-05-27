from gevent.pool import Pool
from gevent.server import StreamServer
import time, os
from threading import Lock, RLock
from exceptions import CommandError, Disconnect
from protocol import ProtocolHandler, Error

    


class Server:
    """
    infrastructure is created here 
    Pool allows users to connect simultaneously (max_clients)

    """
    def __init__(self, host="127.0.0.1", port=31337, max_clients=64, aof_file="appendonly.aof"):
        self._lock = RLock()
        self._pool = Pool(max_clients)

        ##connected to TCP port 31337
        # listen for connection once connceted call connection handler 
        self._server = StreamServer(
            (host, port),
            self.connection_handler,
            spawn=self._pool,
        )

        self._protocol = ProtocolHandler()
        ##this is the redis db
        self._kv = {}
        ##this is the expiry time for keys
        ## [key] => expiry_time
        self._expiry = {}
        self._commands = self.get_commands()
        self._loading = False
        self._aof_file = aof_file
        self.load_persistence()


    """
    Handle a new connection from a client.

    """
    def connection_handler(self, conn, address):
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
        ##validation 
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
    
    
    """
    helper method to verify expiration
    verifies current time, extracts expiry time 
    if the key has expired, it removes the key from 
    both the key-value store and the expiry dictionary
    Lazy Expiration
    """
    def _is_expired(self, key):
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

    """
    Return the append-only file for logging commands.
    """
    def load_persistence(self):
        if not os.path.exists(self._aof_file):
            return
        
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


    """
    Append a command to the append-only file.
    """
    def _append_to_aof(self, command_parts):
        if self._loading:
            return 
        
        with open(self._aof_file, "ab") as f:
            self._protocol.write_response(f, command_parts)

    
    def run(self):
        self._server.serve_forever()
 

if __name__ == "__main__":
    host = os.getenv("REDIS_BIND_HOST", "127.0.0.1")
    port = int(os.getenv("REDIS_PORT", "31337"))

    server = Server(host = host, port = port)
    server.run()
