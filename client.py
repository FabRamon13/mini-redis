from gevent import socket, monkey
from server import ProtocolHandler, CommandError, Error, Server


class Client:
    def __init__(self, host="127.0.0.1", port=31337):
        self._protocol = ProtocolHandler()

        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.connect((host, port))

        self._fh = self._socket.makefile("rwb")

    def execute(self, *args):
        self._protocol.write_response(self._fh, args)

        response = self._protocol.handle_request(self._fh)

        if isinstance(response, Error):
            raise CommandError(response.message)

        return response

    def get(self, key):
        return self.execute("GET", key)

    def set(self, key, value):
        return self.execute("SET", key, value)

    def delete(self, key):
        return self.execute("DELETE", key)

    def flush(self):
        return self.execute("FLUSH")

    def mget(self, *keys):
        return self.execute("MGET", *keys)

    def mset(self, *items):
        return self.execute("MSET", *items)
    
if __name__ == "__main__":
    monkey.patch_all()

    Server().run()