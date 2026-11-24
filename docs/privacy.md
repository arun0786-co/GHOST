# Privacy

## What GHOST reads

Only the folders you add with `ghost add`, and its own notes folder. Inside them, only text files, minus everything listed under "What it reads" in the README: hidden files and folders, key and password files, dependency and build folders, lock and minified files, symlinks, binary files and files over the size limit. A `.ghostignore` file or `skip` in `config.toml` excludes more. If a `.ghostignore` exists but cannot be read, that source is not indexed at all, because indexing without it could pick up exactly what it was meant to keep out.

Your files are opened read-only. GHOST writes only inside `~/.ghost` (or `GHOST_HOME`).

## What it stores

Everything is in `~/.ghost`:

| file | contents |
|---|---|
| `config.toml` | your settings |
| `ghost.db` | the index: paths, sizes and times of indexed files, their text in pieces, open tasks, the timeline |
| `notes/` | the notes from `ghost remember`, one markdown file a day |

The folder is created readable only by you (mode 700) and the database file as mode 600. `ghost doctor` warns if the folder can be read by other users.

Before any text is stored, secret-shaped strings are replaced with `[redacted]`: private key blocks, AWS, GitHub, GitLab, Slack, Stripe, Google and Hugging Face tokens, `sk-` style API keys, JWTs, and `password = ...` / `token: ...` style values that look random. The count shows in `ghost index` and `ghost doctor`. The notes files keep what you typed, but their copy in the index is redacted too.

The redaction is pattern based. It misses formats it does not know, and passwords that are plain words. The skip rules matter more than the redaction.

## Network

GHOST makes no network connections except to a model server for `ghost ask` and `ghost doctor`, and only to a loopback address (`localhost`, `127.0.0.0/8`, `::1`). This is enforced in `model.py`:

- `is_local` checks the url before anything connects, and a remote url in `config.toml` is an error.
- Proxy settings from the environment are ignored, so a request cannot be sent through a proxy on another host.
- Redirects are refused, so a local server cannot pass a request on.
- Ollama's cloud models are never used. Ollama lists them like local models but passes their prompts on to another host (the model's `remote_host`, ollama.com for Ollama's own cloud). GHOST skips any model listed with a remote host or named with a `cloud` tag (`gemma4:cloud`, `gpt-oss:120b-cloud`), and refuses one named in `config.toml` or with `--model`.

The test suite replaces `socket.connect` with a version that fails the test on any address that is not loopback, so every test checks this rule too.

## What a model sees

For `ghost ask`: today's date, your question, and up to 6 passages (about 7000 characters, already redacted) with their paths and file dates. GHOST sends them to the local model server and nowhere else. The model server is a separate program, so check what it logs, keeps or passes on: GHOST refuses Ollama's cloud models, but cannot see what another server does with a request, for example a local proxy for a hosted API. Ollama can be kept local only with `OLLAMA_NO_CLOUD=1`, or `"disable_ollama_cloud": true` in `~/.ollama/server.json` ([Ollama FAQ](https://docs.ollama.com/faq)). GHOST itself does not store questions or answers.

## Forgetting

- `ghost remove NAME` deletes everything indexed from one source: its pieces, tasks and timeline. The files stay.
- To delete a note, edit or delete its file in `~/.ghost/notes`. The next `ghost index` or `ghost remember` updates the index.
- `rm -rf ~/.ghost` deletes everything GHOST knows, including your notes. Copy `notes/` first if you want to keep them.

## Not covered

- The index is not encrypted. Disk encryption (FileVault) protects it at rest. Any program running as your user can read `~/.ghost`, like any other file of yours.
- Backups (Time Machine and others) copy `~/.ghost` like everything else in your home folder.
- Text you index is searchable by anyone who can use your account.
