import unittest
from unittest.mock import patch

from fastapi_cache.config import Settings


class SettingsTests(unittest.TestCase):
    def test_demo_database_delay_defaults_to_zero(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(Settings().demo_db_delay_seconds, 0.0)

    def test_demo_database_delay_can_be_configured(self):
        with patch.dict("os.environ", {"DEMO_DB_DELAY_SECONDS": "1.5"}):
            self.assertEqual(Settings().demo_db_delay_seconds, 1.5)


if __name__ == "__main__":
    unittest.main()
