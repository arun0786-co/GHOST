# Limitations

What is known not to work, or not to work well yet.

## Not tried yet

- **`ghost ask` with a real model.** The client is tested against fake Ollama and OpenAI-style servers on 127.0.0.1, including streaming, errors, redirects and proxies. No model server was installed on the machine it was built on, so answer quality, speed and how well models follow the citation instruction are unknown.
- **Linux.** Built and tested on macOS only. The code avoids macOS-only calls, and the timeline handles file systems without birth times, but nothing has run on Linux.

## Search

- Keywords only. "car" does not find "vehicle". Search by meaning is planned.
- Stemming and stopwords are English. Other languages are matched word for word.
- Underscores and punctuation split words, so `use_context_manager` matches the phrase "context manager".

## What gets read

- Text formats only. No PDF, Word, Pages, images, audio, mail, calendar, messages or browser history yet.
- Files over 1 MB are skipped (`max_file_kb` changes this). UTF-16 files look binary and are skipped.
- Web pages and notebooks are converted to text, so their results have no line numbers.

## Timeline

- Changes are seen only when `ghost index` runs. Several edits between two runs show as one.
- A deletion is dated when indexing notices it, not when it happened.
- Birth times exist on macOS (and BSD). Elsewhere, files already there on the first run only have a last-edited time.
- Git checkouts, copies and unpacked archives set file times, so a fresh clone looks like a burst of new files.

## Tasks

- A TODO inside a string, or a `- [ ]` line inside a code docstring, counts as a task.
- Tasks cannot be marked done from GHOST. Edit the file; the next index drops the task.

## Redaction

- Pattern based: unknown key formats and plain-word passwords get through, and the odd harmless string that looks like a key gets blanked. See docs/privacy.md.

## Size and speed

- The database is about 1.6 times the size of the text it indexes (docs/measurements.md).
- Every run walks the whole source to check file times. On the Python standard library (2,028 files) a run with nothing changed takes 0.12 s. Much bigger sources have not been measured.
