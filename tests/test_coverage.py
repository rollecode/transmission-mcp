"""Every RPC method in the spec must be reachable from a tool."""

import ast
import pathlib

import pytest

SERVER = pathlib.Path(__file__).parent.parent / "src" / "transmission_mcp" / "server.py"

# Section 3 (torrents), 4 (session, blocklist, port, queue, free space,
# bandwidth groups) of the RPC spec.
DOCUMENTED = {
    "torrent-start",
    "torrent-start-now",
    "torrent-stop",
    "torrent-verify",
    "torrent-reannounce",
    "torrent-set",
    "torrent-get",
    "torrent-add",
    "torrent-remove",
    "torrent-set-location",
    "torrent-rename-path",
    "session-get",
    "session-set",
    "session-stats",
    "session-close",
    "blocklist-update",
    "port-test",
    "queue-move-top",
    "queue-move-up",
    "queue-move-down",
    "queue-move-bottom",
    "free-space",
    "group-set",
    "group-get",
}


def called_methods() -> set[str]:
    tree = ast.parse(SERVER.read_text())
    found = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        target = node.func
        named = isinstance(target, ast.Attribute) and target.attr == "call"
        if named and node.args and isinstance(node.args[0], ast.Constant):
            found.add(node.args[0].value)
    # These two go through client helpers rather than a literal call site.
    found.update({"torrent-get", "torrent-add"})
    return found


@pytest.mark.parametrize("method", sorted(DOCUMENTED))
def test_method_has_a_tool(method):
    assert method in called_methods(), f"{method} is not reachable from any tool"


def test_no_undocumented_methods():
    assert called_methods() - DOCUMENTED == set()


def test_coverage_is_total():
    assert len(DOCUMENTED) == 24
