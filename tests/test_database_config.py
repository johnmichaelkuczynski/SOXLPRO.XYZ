import unittest
from unittest.mock import patch

from database_config import database_url


class DatabaseConfigTests(unittest.TestCase):
    def test_neon_overrides_default_database(self):
        self.assertEqual(database_url({
            "NEON_DATABASE_URL": "postgresql://custom/test",
            "DATABASE_URL": "postgresql://default/test",
        }), "postgresql://custom/test")

    def test_standard_database_remains_supported(self):
        self.assertEqual(database_url({"DATABASE_URL": "postgresql://default/test"}),
                         "postgresql://default/test")

    def test_empty_neon_uses_standard_database(self):
        self.assertEqual(database_url({
            "NEON_DATABASE_URL": "  ", "DATABASE_URL": "postgresql://default/test",
        }), "postgresql://default/test")

    def test_missing_credentials_do_not_crash_configuration(self):
        self.assertEqual(database_url({}), "")

    def test_visitor_connection_uses_same_database(self):
        import visitor_counter
        with patch.dict("os.environ", {
            "NEON_DATABASE_URL": "postgresql://custom/test",
            "DATABASE_URL": "postgresql://default/test",
        }), patch.object(visitor_counter.psycopg2, "connect") as connect:
            visitor_counter._connect()
            connect.assert_called_once_with("postgresql://custom/test", connect_timeout=4)
