<center align="center" style="text-align: center;justify-content:center;">
<div align="center" style="text-align: center;justify-content:center;">
<h1 align="center" style="text-align: center;justify-content:center;">

Transmission MCP server

<img style="justify-content:center;text-align: center;width: 95px; height: auto;" width="793" height="411" alt="image" src="https://github.com/user-attachments/assets/abed1a04-d69b-4ab4-a490-d606064df72d" />
<img style="justify-content:center;text-align: center;width: 49px; height: auto;" alt="Transmission" src="public/logo.png" />

</h1>


![Version](https://img.shields.io/badge/version-1.0.0-blue.svg?style=for-the-badge) ![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white) ![Transmission](https://img.shields.io/badge/Transmission-D9291C?style=for-the-badge&logo=transmission&logoColor=white) ![Coverage](https://img.shields.io/badge/RPC_coverage-24%2F24-brightgreen?style=for-the-badge)

</div>
</center>

<hr>

Drive a Transmission daemon from Claude.ai and Claude Code. Every method in the RPC specification is a tool, with every mutator `torrent-set` accepts and every field `torrent-get` returns.

<hr>

## Why not the other options

* Existing Transmission MCP servers cover roughly 19 of the 24 methods, and all of them hard-code one protocol generation
* Transmission 4.1 renamed every RPC string to snake_case; Transmission 3 speaks only the old kebab-case names. This client probes once and then speaks whichever the daemon understands, so it works against both without configuration

## Coverage

| Group | Methods | Covered |
| --- | --- | --- |
| Torrent actions | 5 | 5 |
| Torrent accessor and mutator | 2 | 2 |
| Adding, removing, moving, renaming | 4 | 4 |
| Session | 4 | 4 |
| Queue | 4 | 4 |
| Blocklist, port test, free space | 3 | 3 |
| Bandwidth groups | 2 | 2 |

A test asserts every method in the spec is reachable from a tool.

## Tools

### Reading

| Tool | What you get |
| --- | --- |
| `list_torrents` | Every torrent with state, progress, speeds and a readable status name |
| `get_torrent` | One torrent in full: files, peers, trackers, tracker stats |
| `list_torrent_fields` | The field names `list_torrents` accepts |
| `get_session` | Every session setting and the daemon version |
| `get_session_stats` | Transfer totals, active counts, current speeds |
| `get_free_space` | Free space in a directory the daemon can see |
| `test_port` | Whether the peer port is reachable from outside |
| `get_bandwidth_groups` | Bandwidth groups and their limits |

### Torrents

| Tool | What it does |
| --- | --- |
| `add_torrent` | Add from a magnet link, URL, local .torrent file or base64 metainfo |
| `remove_torrent` | Remove torrents, optionally deleting the data |
| `start_torrents` | Start, respecting the queue |
| `start_torrents_now` | Start immediately, jumping the queue |
| `stop_torrents` | Stop |
| `verify_torrents` | Re-check data against its hashes |
| `reannounce_torrents` | Ask trackers for more peers now |
| `set_torrent` | Every per-torrent setting: limits, labels, file priorities, trackers, seeding rules |
| `move_torrent_data` | Move the data, or record where you already moved it |
| `rename_torrent_path` | Rename a file or directory inside a torrent |

### Queue and session

| Tool | What it does |
| --- | --- |
| `queue_move_top` | To the front of the queue |
| `queue_move_up` | One place up |
| `queue_move_down` | One place down |
| `queue_move_bottom` | To the back |
| `set_session` | Change any session setting |
| `set_bandwidth_group` | Create or change a bandwidth group |
| `update_blocklist` | Fetch a fresh blocklist |
| `shutdown_daemon` | Stop the daemon |

## Setup

```bash
git clone https://github.com/rollecode/transmission-mcp.git
cd transmission-mcp
uv venv && uv pip install -e .
```

```bash
export TRANSMISSION_URL=http://127.0.0.1:9091/transmission/rpc
export TRANSMISSION_USERNAME=...   # only if rpc-authentication-required is on
export TRANSMISSION_PASSWORD=...
```

The URL defaults to `http://127.0.0.1:9091/transmission/rpc`. A `.env` in the working directory works too.

### Claude Code

```bash
claude mcp add transmission -- /path/to/transmission-mcp/.venv/bin/transmission-mcp
```

## Ids

Anywhere a tool takes `ids`, it accepts torrent numbers, hash strings, or the literal `recently-active`. Omitting them means every torrent, which is why `remove_torrent` requires them.

## Development

```bash
uv pip install -e . pytest ruff
.venv/bin/python -m pytest tests
.venv/bin/ruff check .
```

