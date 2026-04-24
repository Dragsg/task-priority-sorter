import unittest
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from app.db import list_stored_messages


class DbTestCase(unittest.TestCase):
    @patch("app.db.ensure_stored_emails_table")
    def test_list_stored_messages_filters_gmail_rows_to_inbox(self, ensure_stored_emails_table):
        cursor = MagicMock()
        cursor.fetchall.return_value = []
        connection = MagicMock()
        connection.cursor.return_value.__enter__.return_value = cursor

        @contextmanager
        def fake_connection():
            yield connection

        with patch("app.db.get_connection", fake_connection):
            list_stored_messages(7, limit=10)

        ensure_stored_emails_table.assert_called_once_with()
        executed_query, executed_params = cursor.execute.call_args.args
        self.assertIn("platform <> 'gmail'", executed_query)
        self.assertIn("""label_ids @> '["INBOX"]'::jsonb""", executed_query)
        self.assertEqual(executed_params, [7, 10])


if __name__ == "__main__":
    unittest.main()
