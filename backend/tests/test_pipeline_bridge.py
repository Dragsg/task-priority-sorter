from unittest.mock import patch

from app.pipeline_bridge import refresh_linked_email_sources


@patch("app.pipeline_bridge.list_new_outlook_messages")
@patch("app.pipeline_bridge.list_recent_outlook_messages")
@patch("app.pipeline_bridge.list_new_messages")
@patch("app.pipeline_bridge.list_recent_messages")
@patch("app.pipeline_bridge.get_outlook_link")
@patch("app.pipeline_bridge.get_gmail_link")
def test_refresh_linked_email_sources_calls_provider_sync_functions(
    get_gmail_link,
    get_outlook_link,
    list_recent_messages,
    list_new_messages,
    list_recent_outlook_messages,
    list_new_outlook_messages,
):
    get_gmail_link.return_value = {"history_id": "123"}
    get_outlook_link.return_value = {"last_received_at": None}
    list_new_messages.return_value = {"messages": [{"id": "g1"}, {"id": "g2"}]}
    list_recent_outlook_messages.return_value = {"messages": [{"id": "o1"}]}

    summary = refresh_linked_email_sources(11, recent_limit=25)

    list_new_messages.assert_called_once_with(11)
    list_recent_outlook_messages.assert_called_once_with(11, limit=25)
    list_recent_messages.assert_not_called()
    list_new_outlook_messages.assert_not_called()
    assert summary["gmail"]["mode"] == "new"
    assert summary["gmail"]["fetchedCount"] == 2
    assert summary["outlook"]["mode"] == "recent"
    assert summary["outlook"]["fetchedCount"] == 1
