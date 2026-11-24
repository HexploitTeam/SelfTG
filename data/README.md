# `!aiml` corpus

`markov_corpus.txt` is the only text the local generator is trained on.

## Where it came from

* **Work:** *The Time Machine* (1895), H. G. Wells.
* **Source:** Project Gutenberg eBook #35, fetched from the GITenberg mirror
  (`GITenberg/The-Time-Machine_35`), because `gutenberg.org` answered 503 from
  this host. The Project Gutenberg header, footer and licence block were
  stripped, illustration markers were removed, and the text was normalised to
  UTF-8 with Unix line endings.
* **Status:** the novel is in the public domain. The Project Gutenberg
  trademark and licence apply to their distribution, not to the underlying
  public-domain text.

## Replacing it

Put any UTF-8 plain text in this file and run `!aiml train` (or just
`!aiml generate`; the model rebuilds when the file's mtime changes).

* At least a few thousand words. Below 300 words the command refuses with the
  word count instead of producing noise.
* Prose works better than lists, code or chat logs.
* Keep it reasonably sized: 100–500 KB gives a good model for a few megabytes
  of RAM.

## The rule

**Never put a Telegram export, a chat dump, or messages copied out of a chat in
this file.** The generator is deliberately fed by a file the owner supplies,
independent of the platform, because Telegram's terms forbid using its data to
train a model. The command never calls `iter_messages` or `get_messages`; the
only input is this path.
