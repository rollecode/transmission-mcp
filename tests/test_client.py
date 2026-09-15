import httpx
import pytest

from transmission_mcp.client import (
    TORRENT_FIELDS,
    TransmissionClient,
    TransmissionError,
    annotate,
    describe_status,
    load_ids,
)


def make_client(handler, **kwargs):
    client = TransmissionClient(url="http://transmission.test/rpc", **kwargs)
    client._http = httpx.Client(transport=httpx.MockTransport(handler))
    return client


def ok(arguments=None):
    return lambda request: httpx.Response(
        200, json={"result": "success", "arguments": arguments or {}}
    )


def test_csrf_409_is_retried_with_the_session_id():
    seen = []

    def handler(request):
        seen.append(request.headers.get("X-Transmission-Session-Id"))
        if len(seen) == 1:
            return httpx.Response(409, headers={"X-Transmission-Session-Id": "abc"})
        return httpx.Response(200, json={"result": "success", "arguments": {}})

    client = make_client(handler)
    client.call("session-get")
    assert seen[1] == "abc"


def test_409_without_a_session_id_is_an_error():
    client = make_client(lambda request: httpx.Response(409))
    with pytest.raises(TransmissionError, match="sent none"):
        client.detect_protocol()
        client._request("session_get", {})


def test_modern_daemon_gets_snake_case_methods():
    sent = []

    def handler(request):
        import json

        sent.append(json.loads(request.content)["method"])
        return httpx.Response(200, json={"result": "success", "arguments": {}})

    client = make_client(handler)
    client.call("torrent-start", ids=[1])
    assert sent[0] == "session_get"
    assert sent[-1] == "torrent_start"


def test_old_daemon_falls_back_to_kebab_case():
    sent = []

    def handler(request):
        import json

        method = json.loads(request.content)["method"]
        sent.append(method)
        if method == "session_get":
            return httpx.Response(200, json={"result": "method name not recognized"})
        return httpx.Response(200, json={"result": "success", "arguments": {}})

    client = make_client(handler)
    client.call("torrent-start", ids=[1])
    assert sent[-1] == "torrent-start"


def test_protocol_is_probed_only_once():
    calls = []

    def handler(request):
        import json

        calls.append(json.loads(request.content)["method"])
        return httpx.Response(200, json={"result": "success", "arguments": {}})

    client = make_client(handler)
    client.call("torrent-stop")
    client.call("torrent-stop")
    assert calls.count("session_get") == 1


def test_a_refusal_names_the_method():
    client = make_client(
        lambda request: httpx.Response(200, json={"result": "no such torrent"})
    )
    client._modern = True
    with pytest.raises(TransmissionError, match="no such torrent"):
        client.call("torrent-get")


def test_get_torrents_asks_for_every_field_by_default():
    sent = {}

    def handler(request):
        import json

        sent.update(json.loads(request.content))
        return httpx.Response(
            200, json={"result": "success", "arguments": {"torrents": []}}
        )

    client = make_client(handler)
    client._modern = True
    client.get_torrents()
    assert sent["arguments"]["fields"] == list(TORRENT_FIELDS)


def test_add_torrent_needs_a_source():
    client = make_client(ok())
    client._modern = True
    with pytest.raises(ValueError, match="Give one of filename"):
        client.add_torrent()


def test_add_torrent_encodes_a_local_file(tmp_path):
    torrent = tmp_path / "x.torrent"
    torrent.write_bytes(b"d8:announce")
    sent = {}

    def handler(request):
        import json

        sent.update(json.loads(request.content))
        return httpx.Response(200, json={"result": "success", "arguments": {}})

    client = make_client(handler)
    client._modern = True
    client.add_torrent(torrent_file=str(torrent))
    assert sent["arguments"]["metainfo"] == "ZDg6YW5ub3VuY2U="


def test_unset_arguments_are_dropped():
    sent = {}

    def handler(request):
        import json

        sent.update(json.loads(request.content))
        return httpx.Response(200, json={"result": "success", "arguments": {}})

    client = make_client(handler)
    client._modern = True
    client.call("torrent-set", ids=[1], labels=None, group="slow")
    assert sent["arguments"] == {"ids": [1], "group": "slow"}


def test_status_names_cover_the_spec_table():
    assert describe_status(0) == "stopped"
    assert describe_status(4) == "downloading"
    assert describe_status(6) == "seeding"
    assert describe_status(None) is None
    assert describe_status(99) == "unknown_99"


def test_annotate_keeps_the_raw_status():
    torrents = annotate([{"status": 6}])
    assert torrents[0] == {"status": 6, "status_name": "seeding"}


def test_load_ids_accepts_every_documented_shape():
    assert load_ids(None) is None
    assert load_ids(7) == [7]
    assert load_ids([7, 8]) == [7, 8]
    assert load_ids("recently-active") == "recently-active"
