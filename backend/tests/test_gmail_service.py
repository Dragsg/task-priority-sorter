import unittest
from unittest.mock import MagicMock, patch

from app.gmail_service import list_new_messages


class GmailServiceTestCase(unittest.TestCase):
    @patch("app.gmail_service.update_gmail_history")
    @patch("app.gmail_service.save_messages")
    @patch("app.gmail_service.get_existing_message_details")
    @patch("app.gmail_service.build_gmail_client")
    def test_list_new_messages_only_keeps_inbox_messages(
        self,
        build_gmail_client,
        get_existing_message_details,
        save_messages,
        update_gmail_history,
    ):
        service = MagicMock()
        build_gmail_client.return_value = service
        service.users.return_value.history.return_value.list.return_value.execute.return_value = {
            "history": [
                {"messagesAdded": [{"message": {"id": "inbox-1"}}, {"message": {"id": "archive-1"}}]}
            ],
            "historyId": "9002",
        }
        get_existing_message_details.return_value = [
            {
                "id": "inbox-1",
                "threadId": "thread-1",
                "historyId": "9001",
                "labelIds": ["INBOX", "UNREAD"],
                "payload": {"headers": []},
                "snippet": "Inbox message",
            },
            {
                "id": "archive-1",
                "threadId": "thread-2",
                "historyId": "9000",
                "labelIds": ["CATEGORY_UPDATES"],
                "payload": {"headers": []},
                "snippet": "Archived message",
            },
        ]

        result = list_new_messages(5, link={"history_id": "123"})

        service.users.return_value.history.return_value.list.assert_called_once_with(
            userId="me",
            startHistoryId="123",
            historyTypes=["messageAdded"],
            labelId="INBOX",
        )
        save_messages.assert_called_once()
        saved_payloads = save_messages.call_args.args[1]
        self.assertEqual(len(saved_payloads), 1)
        self.assertEqual(saved_payloads[0]["source_id"], "inbox-1")
        self.assertEqual([message["id"] for message in result["messages"]], ["inbox-1"])
        self.assertEqual(result["historyId"], "9002")
        update_gmail_history.assert_called_once_with(5, "9002")


if __name__ == "__main__":
    unittest.main()
