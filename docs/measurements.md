# Measurements

Only numbers that were really measured. Anything not measured is listed as such.

Machine: Apple M4 Pro, 24 GB, macOS 15.7.7, Python 3.14.2, SQLite 3.51.1. Measured on 2026-10-27, each index in a fresh `GHOST_HOME`. Times are wall clock for the whole command, including Python start-up (about 0.06 s).

## Python 3.11 standard library source

| | |
|---|---|
| files read | 2,028 (32.8 MB of text) |
| pieces | 23,732 |
| first index | 4.2 s |
| index after 20 files were touched | 0.18 s |
| index with nothing changed | 0.12 s |
| database | 52.3 MB, 1.6 times the text |
| `ghost search asyncio event loop` | 0.13 s |
| `ghost search def` (matches almost every file) | 0.15 s |
| `ghost search '"context manager"' -n 3` | 0.18 s |
| `ghost ask --no-model "how do I decode base64 in python"` | 0.12 s, top passages from `encodings/base64_codec.py`, `test/test_base64.py`, `email/base64mime.py` and `base64.py` |

## A folder of about 20 personal code projects

| | |
|---|---|
| files read | 371 (2.0 MB) |
| pieces | 1,401 |
| open tasks found | 80 |
| first index | 0.45 s |
| index with nothing changed | 0.12 s |
| database | 3.2 MB |
| strings blanked | 6, all of them fake keys in test files |

## Not measured

- Anything with a real model: answer quality, time to first token, tokens per second.
- Sources much bigger than these, such as a whole home folder.
- Linux.
