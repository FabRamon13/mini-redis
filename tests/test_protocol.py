from io import BytesIO
import unittest

from redis_clone.exceptions import CommandError
from redis_clone.protocol import ProtocolHandler


class ProtocolHandlerTests(unittest.TestCase):
    def setUp(self):
        self.protocol = ProtocolHandler()

    def test_bulk_string_reads_exact_payload(self):
        self.assertEqual(
            self.protocol.handle_request(BytesIO(b"$5\r\nhello\r\n")),
            b"hello",
        )

    def test_null_bulk_string_returns_none(self):
        self.assertIsNone(
            self.protocol.handle_request(BytesIO(b"$-1\r\n")),
        )

    def test_bulk_string_rejects_missing_length(self):
        with self.assertRaisesRegex(CommandError, "Missing bulk string length"):
            self.protocol.handle_request(BytesIO(b"$"))

    def test_bulk_string_rejects_invalid_length(self):
        with self.assertRaisesRegex(CommandError, "Invalid bulk string length"):
            self.protocol.handle_request(BytesIO(b"$invalid\r\n"))

    def test_bulk_string_rejects_negative_length_other_than_null(self):
        with self.assertRaisesRegex(CommandError, "Invalid bulk string length"):
            self.protocol.handle_request(BytesIO(b"$-2\r\n"))

    def test_bulk_string_rejects_truncated_payload(self):
        with self.assertRaisesRegex(CommandError, "Truncated bulk string"):
            self.protocol.handle_request(BytesIO(b"$5\r\npa"))

    def test_bulk_string_rejects_invalid_terminator(self):
        with self.assertRaisesRegex(CommandError, "Truncated bulk string"):
            self.protocol.handle_request(BytesIO(b"$5\r\nhelloxx"))

    def test_simple_string_behavior_is_preserved(self):
        self.assertEqual(
            self.protocol.handle_request(BytesIO(b"+PONG\r\n")),
            b"PONG",
        )


if __name__ == "__main__":
    unittest.main()
