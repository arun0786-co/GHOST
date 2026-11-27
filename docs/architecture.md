# Architecture

## Data flow

```text
folders you add, ~/.ghost/notes
        |
        v
files.walk        which files to read (hidden, secret-shaped, generated, binary, big: skipped)
files.read_text   bytes -> text (html and notebooks converted)
redact.redact     secret-shaped strings -> [redacted]
        |
        +--> chunks.split   pieces of about 1200 characters, cut at headings and blank lines
        +--> chunks.tasks   "- [ ]" items, TODO and FIXME lines
        |
        v
~/.ghost/ghost.db   sources, documents, chunks + chunks_fts, tasks, events
        |
        +--> ghost search     fts5 query, best piece per file
        +--> ghost ask        best pieces -> prompt -> model server on 127.0.0.1
        +--> ghost todo       tasks, recently changed files first
        +--> ghost timeline   events by day
```

## Storage

One SQLite file. `pragma user_version` holds the schema version. A newer database is refused instead of being changed.

| table | what it holds |
|---|---|
| `sources` | name, kind (`folder`, `notes` or `git`), path, when it was added and last indexed |
| `documents` | one row per indexed file: path, size, mtime, how many strings were blanked |
| `chunks` | one row per piece: which document, first line |
| `chunks_fts` | fts5 table with the same rowid as `chunks`: `text`, `heading` (the markdown heading above the piece), `place` (the path inside the source) |
| `tasks` | open tasks: document, line, text |
| `events` | the timeline: time, kind (`created`, `edited`, `deleted`, `note`, `task`, `commit`), source, path, detail |

Deleting a source cascades to its documents, chunks, tasks and events. A trigger removes the matching `chunks_fts` rows, also for rows the cascade deletes.

The database uses SQLite's default rollback journal, not WAL. WAL would leave `-wal` and `-shm` files next to the database, and even a read-only connection writes to the `-shm` file. With the rollback journal the index stays one file and `ghost doctor` can open it read-only without changing a byte. The indexer commits every 200 files, so a search started during indexing only waits for the current batch.

Everything in the database except the timeline can be rebuilt from the sources with `ghost index`.

## Indexing

For each source, `indexer.index_source`:

1. walks the folder in a stable order (sorted names, depth first)
2. skips files whose size and mtime match the stored document
3. reads, converts, redacts, splits and extracts tasks from the rest, and replaces their rows
4. removes documents that were not seen. If the file is gone from disk, that is a `deleted` event. If it is still there (now ignored, binary or too big), it leaves the index quietly
5. keeps documents under folders that could not be listed (macOS privacy prompts, permissions), so a denied folder does not look like a mass deletion
6. leaves a source alone when its folder is missing (an unplugged drive)

Timeline events use file times. A new file gets `created` at its birth time where the file system has one (macOS), and `edited` at its mtime if that is more than a minute later. Without a birth time, the first run only records `edited`, because the creation time is unknown. Later runs record new files as `created` at their mtime. The notes source gets no file events: `ghost remember` writes its own `note` and `task` events with the note text.

## Git history

`ghost add --git` adds the commit messages of one repository. `gitlog.py` runs `git log` over the local branches and HEAD, and stores each message with the author's name as a document called `path@commit`, dated by the committer date. File contents and diffs are not read. Each run lists every commit but only stores the new ones. Commits no branch has any more (amended, rebased, deleted branch) leave the index and the timeline. If git fails, the index stays as it was.

A repository's own settings can make git start programs, so `log.showSignature` is overridden, and `GIT_*` variables are removed. Fetching is refused (`GIT_ALLOW_PROTOCOL`, `GIT_NO_LAZY_FETCH`), because in a partial clone `git log` can otherwise contact the remote.

## Search

`chunks_fts` uses the `porter unicode61 remove_diacritics 2` tokenizer: English stemming ("fixing" finds "fixes"), case and accent folding, and splitting on punctuation and underscores.

Every word the user types is quoted before it reaches fts5, so punctuation can never be read as query syntax. `word*` stays a prefix query and `"two words"` stays a phrase. All words have to match. If no file has them all, the words are joined with OR and the output says so.

Ranking is bm25 with weights 1 for `text`, 2 for `heading` and 2 for `place`, so a match in a file name or heading counts double. Results are grouped to the best piece per file. bm25() cannot be used inside a window function, so the ranked rows are put in a materialized CTE first and `row_number()` runs over that. Snippets are fetched afterwards for the rows shown only.

## Ask

1. The question's words, minus English stopwords, are joined with OR.
2. The best pieces are taken: at most 6, at most 2 from one file, about 7000 characters in all (around 2000 tokens, so small local models stay fast).
3. The prompt has the date, numbered passages with their paths and file dates, and an instruction to answer only from them, cite them as `[n]`, and say so when they do not answer the question.
4. The answer streams to the terminal. `<think>` blocks from reasoning models are dropped, also when a tag is split across two pieces of the stream, and so is the reasoning Ollama sends separately in `message.thinking`.
5. Only the passages the answer cites are listed under it, or all of them if it cites none.

The model client (`model.py`) speaks two APIs: Ollama's (`/api/tags`, `/api/show`, `/api/chat`, newline-delimited JSON) and the OpenAI-style one that LM Studio, llama.cpp and others serve (`/v1/models`, `/v1/chat/completions`, server-sent events). Without a configured url it tries 127.0.0.1 on ports 11434, 1234 and 8080 in that order.

Ollama's cloud models are skipped when a model is picked, and refused when one is asked for by name: [`/api/tags`](https://docs.ollama.com/api/tags) lists them with a `remote_host`, and their names carry a `cloud` tag. Ollama passes their prompts on to that host, so they would break the loopback-only rule from behind a loopback address.

Ollama models that reason before answering are asked not to (`think: false`): the reasoning is never shown, and without it the answer starts sooner. `/api/show` lists the `think` values a model accepts, and `false` is sent only when it is one of them, or, where no values are listed (older servers, and models without that metadata), when the model has the `thinking` capability. A model with named levels instead of on and off keeps its default. See Ollama's [thinking docs](https://docs.ollama.com/capabilities/thinking).

Every request goes through one opener with an empty `ProxyHandler` (proxy environment variables are ignored) and a redirect handler that refuses all redirects. `is_local` allows only `localhost` and loopback IP addresses, and is checked before any connection.

## Notes

`ghost remember` appends one line to `~/.ghost/notes/YYYY-MM-DD.md` (`- 14:02 text`, or `- [ ] text` with `--todo`), adds an event, then indexes the notes folder like any other source. Open tasks saved with `--todo` show up in `ghost todo` as normal checkboxes. To change or delete a note, edit the file.

The notes source is found by its kind, not its name. It is called `notes`, or `ghost-notes` if a folder of yours already has that name.

## Choices

- **Standard library only.** Nothing to download, nothing that can phone home, nothing to audit beyond this repository.
- **Keyword search first.** fts5 is fast and exact. It is also easy to explain: a result is there because the words are there. Search by meaning needs a local embedding model, which is a bigger install. It is planned, not missing by accident.
- **Notes are files.** Plain markdown in a folder you can open, back up and edit. The database is an index of them, not their only copy.
- **Loopback only, with no switch to turn that off.** One rule that is easy to check: grep for `_open`. A model server on another machine of yours is reasonable, but it would be a conscious change to this rule, not a config value.
