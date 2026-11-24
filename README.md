# GHOST

## General-purpose Human-Owned Offline System Twin

**A private, local-first personal intelligence system that understands your digital world, preserves your context, and helps you get things done.**

GHOST reads the folders you point it at and the notes you give it, and keeps an index of them on your own computer. With that index you can search everything at once, ask questions that a model on the same computer answers from your own files, list the open tasks scattered through them, and see what changed when.

Nothing leaves the machine. The only network connection GHOST makes is to a model server on a loopback address (127.0.0.1, ::1 or localhost), with proxies and redirects switched off. Everything it knows is in one folder, `~/.ghost`: delete that folder and it forgets everything. Your own files are only read, never changed.

It is a small Python command, `ghost`, for Python 3.11 or newer, standard library only. It was built and tested on macOS. It should work on Linux but has not been tried there.

## Status

| Part | State |
|---|---|
| Local index: one SQLite file with full-text search | done |
| Folders: index new, changed and deleted files, search them | done |
| Notes you add (`ghost remember`), kept as plain markdown | done |
| Open tasks from files and notes (`ghost todo`) | done |
| Timeline of changes (`ghost timeline`) | done |
| Secret-shaped strings blanked before anything is stored | done |
| Answers from a local model (`ghost ask`) | done in code, tested against a fake server. **Not tried with a real model yet** |
| More sources: git history, shell history, browser history, calendar, mail | planned |
| Indexing in the background (launchd or a systemd timer) | planned |
| Search by meaning (local embeddings) | planned |
| Actions: drafts, reminders, follow-ups | planned |

## Install

```bash
uv tool install --editable .        # or: pipx install --editable .
ghost doctor
```

Without installing: `PYTHONPATH=src python3 -m ghost doctor`.

`ghost ask` needs a model server running on this machine. GHOST looks for these on their usual ports:

- [Ollama](https://ollama.com) on 11434, after pulling a model (for example `ollama pull qwen3:8b`)
- LM Studio's local server on 1234
- llama.cpp's `llama-server` on 8080

Or set `[model] url` in `~/.ghost/config.toml`. Everything else works without a model.

## Use

```bash
ghost add ~/notes                         # add a folder and index it
ghost add ~/code --name code
ghost index                               # pick up new, changed and deleted files
ghost search lease rent                   # every word has to match
ghost search '"due date"' invoi*          # phrases and prefixes
ghost search budget --since 2w --source notes
ghost ask "when is the rent due?"         # answered from your files, with sources
ghost remember "the spare key is with Sam"
ghost remember --todo "renew the passport"
ghost notes
ghost todo                                # open "- [ ]" items and TODO / FIXME lines
ghost timeline                            # the last 7 days
ghost timeline --day tuesday
ghost sources
ghost remove code                         # forget a source. its files are not touched
ghost doctor                              # read-only checks
```

### What it reads

Text only: notes and documents (`.md`, `.txt`, `.org`, `.rst`, `.tex` and more), code, config files, web pages (the visible text) and Jupyter notebooks (cells, not outputs). It skips:

- hidden files and folders (`.git`, `.ssh`, `.env` and so on)
- files that usually hold keys or passwords (`*.pem`, `*.key`, `id_rsa*`, `credentials*`, `secrets.*`, keychains, password databases)
- dependency and build folders (`node_modules`, `venv`, `dist`, `build`, `target`, `Library` and others), lock files and minified files
- symlinks, binary files and files over 1 MB

A `.ghostignore` file in a source skips more: one glob pattern per line, matched against names (`private`, `*.log`) or, when the pattern has a `/`, against the path inside the source (`journal/2019`). `skip` and `extra_types` in `config.toml` do the same for every source.

### The timeline

GHOST sees changes when `ghost index` runs. Each change is placed at the time the file system reports: when the file was created (on file systems that keep birth times, like macOS) and when it was last edited. A deleted file is noted when indexing finds it gone. Several edits between two runs show as one, so running `ghost index` often (from cron or a launchd agent) gives a finer timeline.

## Privacy

[docs/privacy.md](docs/privacy.md) has the details. In short: local only, one folder readable only by you, your files untouched, secrets blanked in the index. The index is not encrypted. Disk encryption (FileVault on macOS) protects it at rest.

## Test

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

97 tests, passing on Python 3.11.9, 3.12.13, 3.13.1 and 3.14.2 on macOS. They use temporary folders and fake model servers on 127.0.0.1, and any test that tries to connect to another host fails.

## Files

```text
src/ghost/
  cli.py        the commands
  config.py     ~/.ghost and config.toml
  store.py      the sqlite database: sources, documents, pieces, tasks, timeline
  files.py      which files to read, and the text in them
  chunks.py     cutting text into pieces, finding open tasks
  redact.py     blanking secret-shaped strings
  indexer.py    bringing the index up to date
  search.py     turning words into queries
  ask.py        passages and the prompt for ghost ask
  model.py      the local model client, loopback only
  notes.py      ghost remember
  timeline.py   events by day
  doctor.py     read-only checks
docs/           architecture, privacy, limitations, measurements
```
