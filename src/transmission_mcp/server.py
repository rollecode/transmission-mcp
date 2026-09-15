"""MCP server for Transmission, covering every RPC method."""

import importlib.metadata
import json
import logging
import os

from mcp.server.fastmcp import FastMCP
from mcp.types import Icon

from .client import (
    TORRENT_FIELDS,
    TransmissionClient,
    TransmissionError,
    annotate,
    load_ids,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

try:
    __version__ = importlib.metadata.version("transmission-mcp")
except importlib.metadata.PackageNotFoundError:  # running from a source tree
    __version__ = "0.0.0"

_ICON_BASE = os.getenv("MCP_PUBLIC_URL", "").rstrip("/")
_ICON_SIZES = (48, 96, 256)

mcp = FastMCP(
    "transmission",
    icons=(
        [
            Icon(
                src=f"{_ICON_BASE}/icon.png"
                if size == 256
                else f"{_ICON_BASE}/icon-{size}.png",
                mimeType="image/png",
                sizes=[f"{size}x{size}"],
            )
            for size in _ICON_SIZES
        ]
        if _ICON_BASE
        else None
    ),
    website_url=_ICON_BASE or None,
    instructions=(
        "Control a Transmission daemon: list, add, start, stop, verify and "
        "remove torrents, move and rename their data, reorder the queue, and "
        "read or change session settings. Start with list_torrents to get ids, "
        "then act on them. Ids may be numbers, hash strings, or the literal "
        "'recently-active'. Omitting ids means every torrent, so pass them "
        "explicitly for anything destructive. remove_torrent can delete data "
        "from disk and never does so unless asked."
    ),
)

mcp._mcp_server.version = __version__

_READ = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": False,
}
_WRITE = {
    "readOnlyHint": False,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": False,
}
_DESTRUCTIVE = {**_WRITE, "destructiveHint": True}

_client: TransmissionClient | None = None


def _get_client() -> TransmissionClient:
    global _client
    if _client is None:
        _client = TransmissionClient()
    return _client


def _ok(data: dict) -> str:
    return json.dumps({"status": "success", **data}, indent=2)


def _err(e: Exception) -> str:
    import httpx

    if isinstance(e, TransmissionError):
        msg = str(e)
    elif isinstance(e, httpx.HTTPStatusError):
        status = e.response.status_code
        if status == 401:
            msg = (
                "Transmission rejected the credentials. Check "
                "TRANSMISSION_USERNAME and TRANSMISSION_PASSWORD."
            )
        elif status == 403:
            msg = (
                "Transmission refused the request. Check rpc-host-whitelist "
                "in settings.json."
            )
        else:
            msg = f"Transmission API error (HTTP {status})."
    elif isinstance(e, httpx.ConnectError):
        msg = (
            "Could not connect to Transmission. Check that the daemon is "
            "running and TRANSMISSION_URL points at its RPC endpoint."
        )
    elif isinstance(e, httpx.TimeoutException):
        msg = "Request timed out. Transmission may be busy -- try again."
    else:
        msg = f"{type(e).__name__}: {e}"

    return json.dumps({"status": "error", "message": msg})


# ------------------------------------------------------------------
# Torrents: read
# ------------------------------------------------------------------


@mcp.tool(annotations=_READ)
def list_torrents(
    ids: list | str | None = None, fields: list[str] | None = None
) -> str:
    """List torrents with their state, progress and speeds.

    Args:
        ids: Torrent ids or hash strings, or the literal "recently-active" for
            everything that changed since the last such call. Omit for all
            torrents.
        fields: Which fields to return. Omit for every field. Naming a few
            keeps the response small on a large library.
    """
    try:
        data = _get_client().get_torrents(load_ids(ids), fields)
        torrents = annotate(data.get("torrents") or [])
        return _ok({"count": len(torrents), "torrents": torrents})
    except Exception as e:
        return _err(e)


@mcp.tool(annotations=_READ)
def get_torrent(id: int | str) -> str:
    """Get every field for one torrent, including files, peers and trackers.

    Args:
        id: A torrent id or hash string.
    """
    try:
        data = _get_client().get_torrents(load_ids(id))
        torrents = annotate(data.get("torrents") or [])
        if not torrents:
            return _err(TransmissionError(f"No torrent matches {id!r}."))
        return _ok({"torrent": torrents[0]})
    except Exception as e:
        return _err(e)


@mcp.tool(annotations=_READ)
def list_torrent_fields() -> str:
    """List every field list_torrents can ask for."""
    return _ok({"fields": list(TORRENT_FIELDS)})


# ------------------------------------------------------------------
# Torrents: write
# ------------------------------------------------------------------


@mcp.tool(annotations=_WRITE)
def add_torrent(
    filename: str | None = None,
    torrent_file: str | None = None,
    metainfo: str | None = None,
    download_dir: str | None = None,
    paused: bool = False,
    labels: list[str] | None = None,
    peer_limit: int | None = None,
    bandwidth_priority: int | None = None,
    files_wanted: list[int] | None = None,
    files_unwanted: list[int] | None = None,
    priority_high: list[int] | None = None,
    priority_low: list[int] | None = None,
    priority_normal: list[int] | None = None,
    cookies: str | None = None,
    sequential_download: bool | None = None,
) -> str:
    """Add a torrent from a magnet link, a URL, a local file or raw metainfo.

    Args:
        filename: A magnet link or the URL of a .torrent file.
        torrent_file: Path to a .torrent file on this machine, read and encoded
            for you.
        metainfo: Base64 .torrent contents, if you already have them.
        download_dir: Where to put the data. Defaults to the session setting.
        paused: Add without starting.
        labels: Labels to attach.
        peer_limit: Maximum peers for this torrent.
        bandwidth_priority: -1 low, 0 normal, 1 high.
        files_wanted: Indices of files to download. Omit for all.
        files_unwanted: Indices of files to skip.
        priority_high: Indices of files to fetch first.
        priority_low: Indices of files to fetch last.
        priority_normal: Indices of files at normal priority.
        cookies: Cookies to send when fetching a .torrent URL.
        sequential_download: Download pieces in order rather than rarest first.
    """
    try:
        data = _get_client().add_torrent(
            filename=filename,
            torrent_file=torrent_file,
            metainfo=metainfo,
            **{"download-dir": download_dir, "peer-limit": peer_limit},
            paused=paused,
            labels=labels,
            bandwidthPriority=bandwidth_priority,
            **{
                "files-wanted": files_wanted,
                "files-unwanted": files_unwanted,
                "priority-high": priority_high,
                "priority-low": priority_low,
                "priority-normal": priority_normal,
            },
            cookies=cookies,
            sequentialDownload=sequential_download,
        )
        added = data.get("torrent-added") or data.get("torrent_added")
        duplicate = data.get("torrent-duplicate") or data.get("torrent_duplicate")
        return _ok({"added": added, "duplicate_of": duplicate})
    except Exception as e:
        return _err(e)


@mcp.tool(annotations=_DESTRUCTIVE)
def remove_torrent(ids: list | str | int, delete_local_data: bool = False) -> str:
    """Remove torrents, optionally deleting their downloaded files.

    Args:
        ids: Torrent ids or hash strings. Required -- this tool never defaults
            to every torrent.
        delete_local_data: True also erases the downloaded files from disk.
            This cannot be undone.
    """
    try:
        _get_client().call(
            "torrent-remove",
            ids=load_ids(ids),
            **{"delete-local-data": delete_local_data},
        )
        return _ok({"removed": ids, "deleted_data": delete_local_data})
    except Exception as e:
        return _err(e)


@mcp.tool(annotations=_WRITE)
def start_torrents(ids: list | str | int | None = None) -> str:
    """Start torrents, respecting the download queue.

    Args:
        ids: Torrent ids or hash strings. Omit to start every torrent.
    """
    try:
        _get_client().call("torrent-start", ids=load_ids(ids))
        return _ok({"started": ids or "all"})
    except Exception as e:
        return _err(e)


@mcp.tool(annotations=_WRITE)
def start_torrents_now(ids: list | str | int | None = None) -> str:
    """Start torrents immediately, jumping the download queue.

    Args:
        ids: Torrent ids or hash strings. Omit for every torrent.
    """
    try:
        _get_client().call("torrent-start-now", ids=load_ids(ids))
        return _ok({"started_now": ids or "all"})
    except Exception as e:
        return _err(e)


@mcp.tool(annotations=_WRITE)
def stop_torrents(ids: list | str | int | None = None) -> str:
    """Stop torrents.

    Args:
        ids: Torrent ids or hash strings. Omit to stop every torrent.
    """
    try:
        _get_client().call("torrent-stop", ids=load_ids(ids))
        return _ok({"stopped": ids or "all"})
    except Exception as e:
        return _err(e)


@mcp.tool(annotations=_WRITE)
def verify_torrents(ids: list | str | int | None = None) -> str:
    """Re-check torrent data against its hashes.

    Verification restarts the torrent's progress from zero while it runs.

    Args:
        ids: Torrent ids or hash strings. Omit for every torrent.
    """
    try:
        _get_client().call("torrent-verify", ids=load_ids(ids))
        return _ok({"verifying": ids or "all"})
    except Exception as e:
        return _err(e)


@mcp.tool(annotations=_WRITE)
def reannounce_torrents(ids: list | str | int | None = None) -> str:
    """Ask the trackers for more peers now.

    Args:
        ids: Torrent ids or hash strings. Omit for every torrent.
    """
    try:
        _get_client().call("torrent-reannounce", ids=load_ids(ids))
        return _ok({"reannounced": ids or "all"})
    except Exception as e:
        return _err(e)


@mcp.tool(annotations=_WRITE)
def set_torrent(
    ids: list | str | int,
    bandwidth_priority: int | None = None,
    download_limit: int | None = None,
    download_limited: bool | None = None,
    files_wanted: list[int] | None = None,
    files_unwanted: list[int] | None = None,
    group: str | None = None,
    honors_session_limits: bool | None = None,
    labels: list[str] | None = None,
    location: str | None = None,
    peer_limit: int | None = None,
    priority_high: list[int] | None = None,
    priority_low: list[int] | None = None,
    priority_normal: list[int] | None = None,
    queue_position: int | None = None,
    seed_idle_limit: int | None = None,
    seed_idle_mode: int | None = None,
    seed_ratio_limit: float | None = None,
    seed_ratio_mode: int | None = None,
    sequential_download: bool | None = None,
    tracker_add: list[str] | None = None,
    tracker_list: str | None = None,
    tracker_remove: list[int] | None = None,
    tracker_replace: list | None = None,
    upload_limit: int | None = None,
    upload_limited: bool | None = None,
) -> str:
    """Change any per-torrent setting. Every mutator the RPC accepts is here.

    Args:
        ids: Torrent ids or hash strings.
        bandwidth_priority: -1 low, 0 normal, 1 high.
        download_limit: Download cap in kB/s.
        download_limited: Whether download_limit applies.
        files_wanted: Indices of files to download.
        files_unwanted: Indices of files to skip.
        group: Bandwidth group name.
        honors_session_limits: Whether session speed limits apply.
        labels: Replace the torrent's labels.
        location: New data directory. This only records the path; use
            move_torrent_data to move the files.
        peer_limit: Maximum peers.
        priority_high: File indices to fetch first.
        priority_low: File indices to fetch last.
        priority_normal: File indices at normal priority.
        queue_position: Position in the queue, counting from 0.
        seed_idle_limit: Minutes of no activity before seeding stops.
        seed_idle_mode: 0 global setting, 1 seed_idle_limit, 2 unlimited.
        seed_ratio_limit: Stop seeding at this ratio.
        seed_ratio_mode: 0 global setting, 1 seed_ratio_limit, 2 unlimited.
        sequential_download: Download pieces in order.
        tracker_add: Tracker announce URLs to add. Deprecated by Transmission
            in favour of tracker_list.
        tracker_list: The whole tracker list as text: URLs separated by
            newlines, tiers separated by a blank line.
        tracker_remove: Tracker ids to remove. Deprecated in favour of
            tracker_list.
        tracker_replace: Pairs of tracker id and new URL. Deprecated in favour
            of tracker_list.
        upload_limit: Upload cap in kB/s.
        upload_limited: Whether upload_limit applies.
    """
    try:
        _get_client().call(
            "torrent-set",
            ids=load_ids(ids),
            bandwidthPriority=bandwidth_priority,
            downloadLimit=download_limit,
            downloadLimited=download_limited,
            **{
                "files-wanted": files_wanted,
                "files-unwanted": files_unwanted,
                "peer-limit": peer_limit,
                "priority-high": priority_high,
                "priority-low": priority_low,
                "priority-normal": priority_normal,
                "trackerAdd": tracker_add,
                "trackerList": tracker_list,
                "trackerRemove": tracker_remove,
                "trackerReplace": tracker_replace,
            },
            group=group,
            honorsSessionLimits=honors_session_limits,
            labels=labels,
            location=location,
            queuePosition=queue_position,
            seedIdleLimit=seed_idle_limit,
            seedIdleMode=seed_idle_mode,
            seedRatioLimit=seed_ratio_limit,
            seedRatioMode=seed_ratio_mode,
            sequentialDownload=sequential_download,
            uploadLimit=upload_limit,
            uploadLimited=upload_limited,
        )
        return _ok({"updated": ids})
    except Exception as e:
        return _err(e)


@mcp.tool(annotations=_WRITE)
def move_torrent_data(
    ids: list | str | int, location: str, move: bool = True
) -> str:
    """Move a torrent's data to another directory, or tell it where the data is.

    Args:
        ids: Torrent ids or hash strings.
        location: The target directory.
        move: True moves the existing files there. False only updates the
            recorded path, for data you already moved yourself.
    """
    try:
        _get_client().call(
            "torrent-set-location", ids=load_ids(ids), location=location, move=move
        )
        return _ok({"ids": ids, "location": location, "moved": move})
    except Exception as e:
        return _err(e)


@mcp.tool(annotations=_WRITE)
def rename_torrent_path(id: int | str, path: str, name: str) -> str:
    """Rename a file or directory inside one torrent.

    Args:
        id: A single torrent id or hash string. Renaming is one torrent at a
            time.
        path: The current path, relative to the torrent's own root.
        name: The new name for that one path segment.
    """
    try:
        data = _get_client().call(
            "torrent-rename-path", ids=load_ids(id), path=path, name=name
        )
        return _ok({"renamed": data})
    except Exception as e:
        return _err(e)


# ------------------------------------------------------------------
# Queue
# ------------------------------------------------------------------


@mcp.tool(annotations=_WRITE)
def queue_move_top(ids: list | str | int) -> str:
    """Move torrents to the front of the queue.

    Args:
        ids: Torrent ids or hash strings.
    """
    try:
        _get_client().call("queue-move-top", ids=load_ids(ids))
        return _ok({"moved": ids, "to": "top"})
    except Exception as e:
        return _err(e)


@mcp.tool(annotations=_WRITE)
def queue_move_up(ids: list | str | int) -> str:
    """Move torrents one place up the queue.

    Args:
        ids: Torrent ids or hash strings.
    """
    try:
        _get_client().call("queue-move-up", ids=load_ids(ids))
        return _ok({"moved": ids, "to": "up"})
    except Exception as e:
        return _err(e)


@mcp.tool(annotations=_WRITE)
def queue_move_down(ids: list | str | int) -> str:
    """Move torrents one place down the queue.

    Args:
        ids: Torrent ids or hash strings.
    """
    try:
        _get_client().call("queue-move-down", ids=load_ids(ids))
        return _ok({"moved": ids, "to": "down"})
    except Exception as e:
        return _err(e)


@mcp.tool(annotations=_WRITE)
def queue_move_bottom(ids: list | str | int) -> str:
    """Move torrents to the back of the queue.

    Args:
        ids: Torrent ids or hash strings.
    """
    try:
        _get_client().call("queue-move-bottom", ids=load_ids(ids))
        return _ok({"moved": ids, "to": "bottom"})
    except Exception as e:
        return _err(e)


# ------------------------------------------------------------------
# Session
# ------------------------------------------------------------------


@mcp.tool(annotations=_READ)
def get_session() -> str:
    """Get every session setting and the daemon's version."""
    try:
        return _ok({"session": _get_client().call("session-get")})
    except Exception as e:
        return _err(e)


@mcp.tool(annotations=_READ)
def get_session_stats() -> str:
    """Get transfer totals, active torrent counts and current speeds."""
    try:
        return _ok({"stats": _get_client().call("session-stats")})
    except Exception as e:
        return _err(e)


@mcp.tool(annotations=_WRITE)
def set_session(settings: dict) -> str:
    """Change session settings.

    Args:
        settings: Setting names exactly as get_session reports them, mapped to
            new values. For example {"speed-limit-down": 5000,
            "speed-limit-down-enabled": true} or {"download-dir":
            "/mnt/media"}. Read get_session first to see the current names and
            values, which differ between Transmission 3 and 4.
    """
    try:
        _get_client().call("session-set", **settings)
        return _ok({"updated": sorted(settings)})
    except Exception as e:
        return _err(e)


@mcp.tool(annotations=_READ)
def test_port() -> str:
    """Check whether the peer port is reachable from outside."""
    try:
        return _ok({"result": _get_client().call("port-test")})
    except Exception as e:
        return _err(e)


@mcp.tool(annotations=_WRITE)
def update_blocklist() -> str:
    """Download a fresh copy of the blocklist and report its size."""
    try:
        return _ok({"result": _get_client().call("blocklist-update")})
    except Exception as e:
        return _err(e)


@mcp.tool(annotations=_READ)
def get_free_space(path: str) -> str:
    """Get free space in a directory the daemon can see.

    Args:
        path: A directory path on the machine running Transmission, not on this
            one.
    """
    try:
        return _ok({"result": _get_client().call("free-space", path=path)})
    except Exception as e:
        return _err(e)


@mcp.tool(annotations=_DESTRUCTIVE)
def shutdown_daemon() -> str:
    """Shut the Transmission daemon down.

    Every torrent stops and the daemon exits. Nothing here can start it again.
    """
    try:
        _get_client().call("session-close")
        return _ok({"shutdown": True})
    except Exception as e:
        return _err(e)


# ------------------------------------------------------------------
# Bandwidth groups
# ------------------------------------------------------------------


@mcp.tool(annotations=_READ)
def get_bandwidth_groups(group: str | None = None) -> str:
    """Get bandwidth groups and their speed limits.

    Args:
        group: One group name. Omit for every group.
    """
    try:
        return _ok({"result": _get_client().call("group-get", group=group)})
    except Exception as e:
        return _err(e)


@mcp.tool(annotations=_WRITE)
def set_bandwidth_group(
    name: str,
    honors_session_limits: bool | None = None,
    speed_limit_down: int | None = None,
    speed_limit_down_enabled: bool | None = None,
    speed_limit_up: int | None = None,
    speed_limit_up_enabled: bool | None = None,
) -> str:
    """Create or change a bandwidth group.

    Args:
        name: Group name. A name that does not exist yet is created.
        honors_session_limits: Whether the session's own limits also apply.
        speed_limit_down: Download cap for the group in kB/s.
        speed_limit_down_enabled: Whether the download cap applies.
        speed_limit_up: Upload cap for the group in kB/s.
        speed_limit_up_enabled: Whether the upload cap applies.
    """
    try:
        _get_client().call(
            "group-set",
            name=name,
            honorsSessionLimits=honors_session_limits,
            **{
                "speed-limit-down": speed_limit_down,
                "speed-limit-down-enabled": speed_limit_down_enabled,
                "speed-limit-up": speed_limit_up,
                "speed-limit-up-enabled": speed_limit_up_enabled,
            },
        )
        return _ok({"group": name})
    except Exception as e:
        return _err(e)


def main() -> None:
    import argparse

    from dotenv import find_dotenv, load_dotenv

    dotenv_path = find_dotenv(usecwd=True)
    if dotenv_path and load_dotenv(dotenv_path, override=False):
        logger.info("Loaded .env from %s", dotenv_path)

    parser = argparse.ArgumentParser(prog="transmission-mcp")
    parser.add_argument(
        "--transport",
        choices=("stdio", "http"),
        default=os.getenv("MCP_TRANSPORT", "stdio"),
    )
    parser.add_argument("--host", default=os.getenv("MCP_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("MCP_PORT", "8441")))
    args = parser.parse_args()

    if args.transport == "stdio":
        mcp.run(transport="stdio")
        return

    if args.host not in ("127.0.0.1", "::1", "localhost"):
        raise SystemExit(
            f"refusing to listen on {args.host}: this server has no login of "
            "its own. Keep it on the local machine and put a proxy in front."
        )

    mcp.settings.host = args.host
    mcp.settings.port = args.port
    logger.info("Listening on http://%s:%d/mcp", args.host, args.port)
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
