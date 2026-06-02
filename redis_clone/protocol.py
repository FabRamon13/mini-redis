from collections import namedtuple
from io import BytesIO

from redis_clone.exceptions import CommandError, Disconnect


Error = namedtuple("Error", ("message",))


class ProtocolHandler:
    def __init__(self):
        ## Map of Redis protocol type indicators to their corresponding handler methods
        self.handlers = {
            b"+": self.handle_simple_string,
            b"-": self.handle_error,
            b":": self.handle_integer,
            b"$": self.handle_string,
            b"*": self.handle_array,
            b"%": self.handle_dict,
        }
    def handle_request(self, socket_file):
        first_byte = socket_file.read(1)

        if not first_byte:
            raise Disconnect()

        try:
            return self.handlers[first_byte](socket_file)
        except KeyError:
            raise CommandError(f"Unknown protocol type: {first_byte}") 

    def write_response(self, socket_file, data):
    
        buf = BytesIO()
        self._write(buf, data)
        socket_file.write(buf.getvalue())
        ##sends through TCP conn
        socket_file.flush()
        
    def _write(self, buf, data):
        if isinstance(data, str):
            data = data.encode("utf-8")

        if isinstance(data, bytes):
            buf.write(
                b"$" + str(len(data)).encode("utf-8") +
                b"\r\n" + data + b"\r\n"
            )

        elif isinstance(data, int):
            buf.write(
                b":" + str(data).encode("utf-8") + b"\r\n"
            )

        elif isinstance(data, Error):
            message = data.message
            if isinstance(message, str):
                message = message.encode("utf-8")

            buf.write(b"-" + message + b"\r\n")

        elif isinstance(data, (list, tuple)):
            buf.write(
                b"*" + str(len(data)).encode("utf-8") + b"\r\n"
            )

            for item in data:
                self._write(buf, item)

        elif isinstance(data, dict):
            buf.write(
                b"%" + str(len(data)).encode("utf-8") + b"\r\n"
            )

            for key, value in data.items():
                self._write(buf, key)
                self._write(buf, value)

        elif data is None:
            buf.write(b"$-1\r\n")

        else:
            raise CommandError(f"unrecognized type: {type(data)}")
    
    ##parse to handle simple strings 
    def handle_simple_string(self, socket_file):
        return socket_file.readline().rstrip(b"\r\n")

    ##handling errors 
    def handle_error(self, socket_file):
        return Error(socket_file.readline().rstrip(b"\r\n"))

    ##handling integers 
    def handle_integer(self, socket_file):
        return int(socket_file.readline().rstrip(b"\r\n"))

    def handle_string(self, socket_file):
        length_line = socket_file.readline()

        if not length_line:
            raise CommandError("Missing bulk string length")

        try:
            length = int(length_line.rstrip(b"\r\n"))
        except ValueError:
            raise CommandError("Invalid bulk string length")

        if length == -1:
            return None

        if length < -1:
            raise CommandError("Invalid bulk string length")

        payload = socket_file.read(length)
        terminator = socket_file.read(2)

        if len(payload) != length or terminator != b"\r\n":
            raise CommandError("Truncated bulk string")

        return payload

    def handle_array(self, socket_file):
        num_elements = int(socket_file.readline().rstrip(b"\r\n"))

        return [
            self.handle_request(socket_file)
            for _ in range(num_elements)
        ]

    def handle_dict(self, socket_file):
        num_items = int(socket_file.readline().rstrip(b"\r\n"))

        elements = [
            self.handle_request(socket_file)
            for _ in range(num_items * 2)
        ]

        return dict(zip(elements[::2], elements[1::2]))
