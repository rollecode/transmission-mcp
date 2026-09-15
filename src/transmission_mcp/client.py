"""Client for the Transmission RPC API.

Transmission 4.1 renamed every RPC string to snake_case and added JSON-RPC 2.0.
The old bespoke protocol with kebab-case and camelCase still works in 4.x but is
deprecated, and 3.x speaks only the old one. This client probes once and then
speaks whichever the daemon understands.

Ref: https://github.com/transmission/transmission/blob/main/docs/rpc-spec.md
"""

import base64
import logging
import os
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

# Transmission answers the first unauthenticated request with 409 and the
# session id it wants echoed back on every subsequent call.
_CSRF_HEADER = "X-Transmission-Session-Id"

# Method names differ between the two protocol generations. Everything else in
# a request is either an id list or a field name, both of which are translated
# by the same table.
_MODERN_METHODS = {
    "torrent-start": "torrent_start",
    "torrent-start-now": "torrent_start_now",
    "torrent-stop": "torrent_stop",
    "torrent-verify": "torrent_verify",
    "torrent-reannounce": "torrent_reannounce",
    "torrent-set": "torrent_set",
    "torrent-get": "torrent_get",
    "torrent-add": "torrent_add",
    "torrent-remove": "torrent_remove",
    "torrent-set-location": "torrent_set_location",
    "torrent-rename-path": "torrent_rename_path",
    "session-get": "session_get",
    "session-set": "session_set",
    "session-stats": "session_stats",
    "session-close": "session_close",
    "blocklist-update": "blocklist_update",
    "port-test": "port_test",
    "queue-move-top": "queue_move_top",
    "queue-move-up": "queue_move_up",
    "queue-move-down": "queue_move_down",
    "queue-move-bottom": "queue_move_bottom",
    "free-space": "free_space",
    "group-set": "group_set",
    "group-get": "group_get",
}

# Every field torrent_get can return. Asking for all of them is the default so
# a caller never has to know the list exists, but it is exposed so a caller
# that wants a small response can name just what it needs.
TORRENT_FIELDS = (
    "activityDate",
    "addedDate",
    "availability",
    "bandwidthPriority",
    "comment",
    "corruptEver",
    "creator",
    "dateCreated",
    "desiredAvailable",
    "doneDate",
    "downloadDir",
    "downloadLimit",
    "downloadLimited",
    "downloadedEver",
    "editDate",
    "error",
    "errorString",
    "eta",
    "etaIdle",
    "fileCount",
    "fileStats",
    "files",
    "group",
    "hashString",
    "haveUnchecked",
    "haveValid",
    "honorsSessionLimits",
    "id",
    "isFinished",
    "isPrivate",
    "isStalled",
    "labels",
    "leftUntilDone",
    "magnetLink",
    "manualAnnounceTime",
    "maxConnectedPeers",
    "metadataPercentComplete",
    "name",
    "peer-limit",
    "peers",
    "peersConnected",
    "peersFrom",
    "peersGettingFromUs",
    "peersSendingToUs",
    "percentComplete",
    "percentDone",
    "pieceCount",
    "pieceSize",
    "pieces",
    "primary-mime-type",
    "priorities",
    "queuePosition",
    "rateDownload",
    "rateUpload",
    "recheckProgress",
    "secondsDownloading",
    "secondsSeeding",
    "seedIdleLimit",
    "seedIdleMode",
    "seedRatioLimit",
    "seedRatioMode",
    "sequentialDownload",
    "sizeWhenDone",
    "startDate",
    "status",
    "trackerList",
    "trackerStats",
    "trackers",
    "totalSize",
    "torrentFile",
    "uploadLimit",
    "uploadLimited",
    "uploadRatio",
    "uploadedEver",
    "wanted",
    "webseeds",
    "webseedsSendingToUs",
)

# Numeric status values, from the spec's status table.
TORRENT_STATUS = {
    0: "stopped",
    1: "queued_to_verify",
    2: "verifying",
    3: "queued_to_download",
    4: "downloading",
    5: "queued_to_seed",
    6: "seeding",
}


class TransmissionError(RuntimeError):
    """Transmission answered with a result other than success."""


class TransmissionClient:
    def __init__(
        self,
        url: str | None = None,
        username: str | None = None,
        password: str | None = None,
        timeout: float = 30.0,
    ):
        self.url = (
            url
            or os.getenv("TRANSMISSION_URL")
            or "http://127.0.0.1:9091/transmission/rpc"
        )
        username = username or os.getenv("TRANSMISSION_USERNAME")
        password = password or os.getenv("TRANSMISSION_PASSWORD")

        auth = (username, password) if username else None
        self._http = httpx.Client(timeout=timeout, auth=auth)
        self._session_id = ""
        self._modern: bool | None = None

    # -- protocol ---------------------------------------------------------

    def _method_name(self, method: str) -> str:
        if self._modern:
            return _MODERN_METHODS.get(method, method.replace("-", "_"))
        return method

    def detect_protocol(self) -> bool:
        """Probe once for the snake_case protocol, remembering the answer.

        A daemon that does not know `session_get` rejects it, which is the
        signal to fall back to the deprecated names rather than guess from a
        version string the old daemons report differently.
        """
        if self._modern is not None:
            return self._modern
        try:
            self._request("session_get", {})
            self._modern = True
        except (TransmissionError, httpx.HTTPStatusError):
            self._modern = False
        return self._modern

    # -- transport --------------------------------------------------------

    def _request(self, method: str, arguments: dict) -> dict:
        body = {"method": method, "arguments": arguments}
        response = self._http.post(
            self.url,
            json=body,
            headers={_CSRF_HEADER: self._session_id} if self._session_id else {},
        )

        # 409 carries the session id to use from now on; the request itself is
        # not an error and is retried once with the header in place.
        if response.status_code == 409:
            self._session_id = response.headers.get(_CSRF_HEADER, "")
            if not self._session_id:
                raise TransmissionError(
                    "Transmission asked for a session id but sent none."
                )
            response = self._http.post(
                self.url, json=body, headers={_CSRF_HEADER: self._session_id}
            )

        response.raise_for_status()
        data = response.json()

        result = data.get("result")
        if result != "success":
            raise TransmissionError(f"Transmission refused {method}: {result}")
        return data.get("arguments") or {}

    def call(self, method: str, **arguments) -> dict:
        """Call one RPC method, dropping unset arguments."""
        self.detect_protocol()
        payload = {k: v for k, v in arguments.items() if v is not None}
        return self._request(self._method_name(method), payload)

    # -- torrents ---------------------------------------------------------

    def get_torrents(
        self, ids: list | str | None = None, fields: list[str] | None = None
    ) -> dict:
        return self.call(
            "torrent-get", ids=ids, fields=list(fields or TORRENT_FIELDS)
        )

    def add_torrent(self, **arguments) -> dict:
        """Add a torrent from a magnet link, URL, file path or raw metainfo."""
        path = arguments.pop("torrent_file", None)
        if path:
            arguments["metainfo"] = base64.b64encode(
                Path(path).expanduser().read_bytes()
            ).decode("ascii")
        if not arguments.get("filename") and not arguments.get("metainfo"):
            raise ValueError(
                "Give one of filename (magnet or URL), torrent_file (local "
                "path) or metainfo (base64)."
            )
        return self.call("torrent-add", **arguments)

    def close(self) -> None:
        self._http.close()


def describe_status(value: int | None) -> str | None:
    """Render torrent status as its name, since the wire value is a bare int."""
    if value is None:
        return None
    return TORRENT_STATUS.get(value, f"unknown_{value}")


def annotate(torrents: list[dict]) -> list[dict]:
    """Add a readable status to each torrent without dropping the raw value."""
    for torrent in torrents:
        if "status" in torrent:
            torrent["status_name"] = describe_status(torrent["status"])
    return torrents


def load_ids(ids: list | str | int | None) -> list | str | None:
    """Normalise an id argument into what the RPC accepts.

    Transmission takes a list of ids or hashes, the string "recently-active",
    or nothing at all, which means every torrent.
    """
    if ids is None:
        return None
    if isinstance(ids, str):
        return ids
    if isinstance(ids, int):
        return [ids]
    return list(ids)


__all__ = [
    "TORRENT_FIELDS",
    "TORRENT_STATUS",
    "TransmissionClient",
    "TransmissionError",
    "annotate",
    "describe_status",
    "load_ids",
]
