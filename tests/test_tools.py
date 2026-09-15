"""Call real tools and check the RPC requests they build."""

import json

import httpx
import pytest

from transmission_mcp import server


@pytest.fixture(autouse=True)
def transport():
    server._client = None
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen["method"] = body["method"]
        seen["arguments"] = body["arguments"]
        return httpx.Response(
            200,
            json={"result": "success", "arguments": {"torrents": [{"id": 1, "status": 6}]}},
        )

    client = server._get_client()
    client._http = httpx.Client(transport=httpx.MockTransport(handler))
    yield seen
    server._client = None


def test_listing_asks_for_every_field(transport):
    result = json.loads(server.list_torrents())
    assert result["status"] == "success"
    assert transport["method"] == "torrent_get"
    assert "hashString" in transport["arguments"]["fields"]


def test_a_listed_torrent_carries_a_readable_status(transport):
    result = json.loads(server.list_torrents())
    assert result["torrents"][0]["status_name"] == "seeding"


def test_ids_accept_the_recently_active_literal(transport):
    server.list_torrents(ids="recently-active")
    assert transport["arguments"]["ids"] == "recently-active"


def test_a_single_id_becomes_a_list(transport):
    server.stop_torrents(ids=4)
    assert transport["method"] == "torrent_stop"
    assert transport["arguments"]["ids"] == [4]


def test_removing_does_not_delete_data_unless_asked(transport):
    server.remove_torrent(ids=[1])
    assert transport["arguments"]["delete-local-data"] is False


def test_removing_can_delete_data(transport):
    server.remove_torrent(ids=[1], delete_local_data=True)
    assert transport["arguments"]["delete-local-data"] is True


def test_set_torrent_sends_only_what_changed(transport):
    server.set_torrent(ids=[1], upload_limit=50)
    assert transport["arguments"] == {"ids": [1], "uploadLimit": 50}


def test_adding_needs_a_source(transport):
    result = json.loads(server.add_torrent())
    assert result["status"] == "error"
    assert "filename" in result["message"]


def test_annotations_match_what_each_tool_does():
    import asyncio

    registered = {t.name: t for t in asyncio.run(server.mcp.list_tools())}
    assert registered["list_torrents"].annotations.readOnlyHint is True
    assert registered["remove_torrent"].annotations.destructiveHint is True
    assert registered["shutdown_daemon"].annotations.destructiveHint is True
    assert registered["add_torrent"].annotations.readOnlyHint is False
