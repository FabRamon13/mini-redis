import socket
from redis_clone.exceptions import CommandError
from redis_clone.protocol import ProtocolHandler, Error

class Client:
    def __init__(self, host="127.0.0.1", port=31337):
        self._protocol = ProtocolHandler()

        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.connect((host, port))

        self._fh = self._socket.makefile("rwb")

    """
    sends out commands 
    """
    def execute(self, *args):
        self._protocol.write_response(self._fh, args)

        response = self._protocol.handle_request(self._fh)

        if isinstance(response, Error):
            raise CommandError(response.message)

        return response
    """
    method to close socket
    """
    def close(self):
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
