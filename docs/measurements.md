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

## Answers from a local model

Measured on 2026-10-29 on the same machine, with Ollama 0.40.12 (the Homebrew cask `ollama-app`) and `qwen3.5:4b`. For this Mac Ollama pulled an MLX build: 4.5B parameters, nvfp4, 4.0 GB on disk. The test set is six short notes (a lease, car insurance, meeting minutes, a dentist appointment, a packing list, a recipe), six questions they answer and two they do not.

| | |
|---|---|
| answerable questions answered right | 6 of 6 in each of 7 runs (42 of 42) |
| the two questions the notes do not answer | declined in every run read in full (3 of 7), for example "The provided passages do not answer the question." |
| answer present in the passages handed to the model | 6 of 6 |
| first answer of the day, loading the model | 5.97 s to the first word, 6.23 s in all |
| answers with the model loaded (final run) | 0.19 to 0.41 s to the first word, 0.57 to 1.26 s in all |
| `ghost ask "when does the car insurance renew?"`, the whole command | 0.72 s |
| generation speed on a 300-token answer | 28.7 tokens/s |
| memory, from Ollama's `/api/ps` | 5.1 GB after the short answers, 7.6 GB after the thinking runs below |

With thinking left on (the model's default), the first word came after 16.2 to 18.6 s instead of 0.10 to 0.16 s, for the same answers (two questions, two runs each). ghost turns thinking off for models that allow it.

Before the prompt asked for plain text, 6 of 24 answers over three runs used markdown bold, which a terminal shows as asterisks. After, none of 32 answers over four runs did.

Prompt reading speeds are left out: Ollama had cached the repeated prompts, so the numbers were not real.

## Not measured

- Other models and model servers (LM Studio, llama.cpp), and questions over real notes instead of the test set.
- Sources much bigger than these, such as a whole home folder.
- Linux.
