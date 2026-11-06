import unittest
from unittest.mock import MagicMock, patch

import setup_database


class DatabaseSetupTests(unittest.TestCase):
    def test_setup_creates_all_tables_in_one_transaction_and_closes(self):
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        with patch.object(setup_database.db, "get_conn", return_value=connection):
            setup_database.initialize()
        sql = "\n".join(call.args[0] for call in cursor.execute.call_args_list)
        for name in ("market_state", "market_worker_health", "benchmark_quotes",
                     "billing_webhook_events", "site_visitors", "site_visit_stats",
                     "site_visit_sessions", "diagnostic_runs"):
            self.assertIn("CREATE TABLE IF NOT EXISTS " + name, sql)
        self.assertNotIn("DROP ", sql)
        self.assertNotIn("DELETE ", sql)
        connection.close.assert_called_once()

    def test_setup_closes_on_failure(self):
        connection = MagicMock()
        connection.cursor.return_value.__enter__.return_value.execute.side_effect = RuntimeError()
        with patch.object(setup_database.db, "get_conn", return_value=connection):
            with self.assertRaises(RuntimeError):
                setup_database.initialize()
        connection.close.assert_called_once()
