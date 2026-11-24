# `!aiml` corpus

`data/corpus/` is the only text the local generator trains on: one UTF-8 `.txt`
file per source, all read together by `!aiml train`.

## What ships

* **File:** `the-time-machine.txt`
* **Work:** *The Time Machine* (1895), H. G. Wells.
* **Source:** Project Gutenberg eBook #35, fetched from the GITenberg mirror
  (`GITenberg/The-Time-Machine_35`), because `gutenberg.org` answered 503 from
  this host. The Project Gutenberg header, footer and licence block were
  stripped, illustration markers were removed, and the text was normalised to
  UTF-8 with Unix line endings.
* **Status:** the novel is in the public domain. The Project Gutenberg
  trademark and licence apply to their distribution, not to the underlying
  public-domain text.

## Adding a source

Drop another `.txt` file into `data/corpus/`. That is the whole procedure: the
model's cache key includes every source's name, mtime and size, so a new or
edited file is picked up by the next `!aiml gen`, `say`, `para` or `next`
without a command. `!aiml train` forces a rebuild and prints a per-source
report; `!aiml corpus` lists what is loaded.

Limits, all enforced with a message rather than a silent skip:

* **One source per file.** Chapter dumps and whole books both work; splitting
  into files is for telling sources apart, not for quality.
* **At most 12 files** in the folder. Beyond that the command refuses and says
  how many it found, because a directory of thousands of files is a different
  feature.
* **At least 300 words in total.** Below that every generation command refuses
  with the word count.
* **Keep the total near 1 MB.** Counts for three orders cost roughly 15 MB of
  memory per 180 KB of prose; four times the text is four times the model.
* **Prose works better than lists, code or chat logs.** Dialogue-heavy text
  produces dialogue; reference text produces fragments.
* **Name files for the text**, not for the person who sent it
  (`the-time-machine.txt`, not `ali-sent-this.txt`).

## The rule

**Never put a Telegram export, a chat dump, or messages copied out of a chat in
this folder.** The generator is deliberately fed by files the owner supplies,
independent of the platform, because Telegram's terms forbid using its data to
train a model. The command never calls `iter_messages` or `get_messages`; the
only input is this directory.
