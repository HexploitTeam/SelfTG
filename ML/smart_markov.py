"""Interpolated variable-order Markov chain used by the `!aiml` commands.

What changed from the first version
-----------------------------------
The first engine trained a single order (2) and picked the next word uniformly
from a list, which made every continuation equally likely and produced the
flat, wandering text a plain bigram is known for. This one keeps counts for
every order from 1 up to ``order`` and blends them when it samples:

* the longest matching state leads (it saw these exact words);
* the shorter states refine the tail, so a state seen once still has sensible
  continuations instead of dead-ending after two words;
* counts are weights, not a uniform choice, so "the" followed by "time" twice
  as often as "the" followed by "machine" is reflected in the output.

Temperature reshapes the blended weights: below 1 the most likely word wins
almost every time, above 1 the long tail gets a turn. A seed continues from
its *last* words (a suffix), matched against the longest state the corpus
actually contains, which is what "write more like this" means for a Markov
chain.

No files, no network, no neural network, no training on anything but the
corpus the caller passes to :meth:`train`. Counts for three orders over the
180 KB corpus cost roughly 15 MB of Python objects, built once per process.
"""
import random
from collections import Counter, defaultdict

# Words that end a sentence; generation stops on one once it has enough text
SENTENCE_END = (".", "!", "?", "…")

MAX_ORDER = 4


class SmartMarkov:
    """A variable-order chain over sentence-ish strings."""

    def __init__(self, order=3):
        self.order = max(1, min(int(order), MAX_ORDER))
        # models[k] maps a k-word history to a Counter of what followed it
        self.models = [None] + [defaultdict(Counter) for _ in range(self.order)]
        self.starts = Counter()          # weighted sentence openings
        self.word_counter = Counter()
        self.total_words = 0
        self.sentences = 0

    #------------------------------
    #Training
    #------------------------------

    def train(self, texts):
        """Learn from an iterable of sentences. Returns ``self``."""
        for text in texts or ():
            words = str(text).split()
            if len(words) < 2:
                continue

            self.sentences += 1
            self.total_words += len(words)
            self.word_counter.update(words)
            self.starts[tuple(words[:self.order])] += 1

            # States are keyed in lowercase so "the time" finds "the Time";
            # the words that come back out keep the corpus's capitalisation.
            keys = [word.lower() for word in words]
            for index, word in enumerate(words):
                for size in range(1, min(self.order, index) + 1):
                    state = tuple(keys[index - size:index])
                    self.models[size][state][word] += 1
        return self

    #------------------------------
    #Sampling
    #------------------------------

    def _blend(self, history, temperature):
        """Mix the counts of every matching order into one weight per word."""
        blended = {}
        weight = 1.0
        # Only the last `order` words can match a state. Slicing here keeps the
        # cost per generated word fixed instead of lowercasing the whole
        # sentence again on every step of the walk.
        keys = [word.lower() for word in history[-self.order:]]

        for size in range(min(self.order, len(keys)), 0, -1):
            table = self.models[size].get(tuple(keys[-size:]))
            if not table:
                continue
            total = sum(table.values())
            scale = weight / total
            for word, count in table.items():
                blended[word] = blended.get(word, 0.0) + count * scale
            weight *= 0.55          # shorter contexts refine, never dominate

        if not blended or temperature <= 0:
            return blended

        power = 1.0 / max(float(temperature), 0.05)
        return {word: value ** power for word, value in blended.items()}

    @staticmethod
    def _pick(blended, history, rng):
        """Sample one word, avoiding an immediate repeat when there is a choice."""
        choices = dict(blended)
        if len(choices) > 1 and history:
            choices.pop(history[-1], None)
        if not choices:
            choices = dict(blended)
        words = list(choices)
        weights = [choices[word] for word in words]
        return rng.choices(words, weights=weights, k=1)[0]

    def _walk(self, history, max_words, temperature, rng, min_words=8):
        """Append words to `history` until a sentence ends or `max_words`."""
        out = list(history)
        while len(out) < max_words:
            blended = self._blend(out, temperature)
            if not blended:
                break
            word = self._pick(blended, out, rng)
            out.append(word)
            if len(out) >= min_words and word.endswith(SENTENCE_END):
                break
        return out[len(history):]

    #------------------------------
    #Generation
    #------------------------------

    def generate(self, seed=None, max_words=30, temperature=1.0, rng=None):
        """Return one sentence-ish string, continuing `seed` when given."""
        rng = rng or random
        max_words = max(2, min(int(max_words), 400))
        seed_words = str(seed or "").split()

        if seed_words:
            # Continue from the longest suffix of the seed the corpus knows; if
            # that walk dies immediately, a shorter suffix gets a turn.
            target = max(max_words, len(seed_words) + 8)
            best = []
            for size in range(min(self.order, len(seed_words)), 0, -1):
                context = seed_words[-size:]
                key = tuple(word.lower() for word in context)
                if key not in self.models[size]:
                    continue
                tail = self._walk(context, target, temperature, rng)
                if len(tail) > len(best):
                    best = tail
                if len(best) >= 3:
                    break
            return " ".join(seed_words + best)

        if not self.starts:
            return ""

        opening = rng.choices(
            list(self.starts), weights=list(self.starts.values()), k=1
        )[0]
        return " ".join(list(opening) + self._walk(opening, max_words, temperature, rng))

    def paragraph(self, sentences=3, max_words=30, temperature=1.0, rng=None):
        """Several sentences, never repeating one."""
        rng = rng or random
        lines = []
        for _ in range(max(1, min(int(sentences), 10))):
            for _attempt in range(4):
                line = self.generate(max_words=max_words, temperature=temperature, rng=rng)
                if line and line not in lines and len(line.split()) >= 4:
                    lines.append(line)
                    break
        return " ".join(lines)

    @staticmethod
    def _core(word):
        """A word without the punctuation that only marks its sentence end."""
        return word.strip("\"'()[].,!?;:—–…") or word

    def next_words(self, text, limit=5):
        """Most likely continuations of `text`, as ``(word, probability)``.

        Punctuation variants are merged (``Traveller`` and ``Traveller.`` are
        one answer, with their odds added) so the listing reads like words.
        """
        history = str(text or "").split()
        if not history:
            return []

        blended = self._blend(history, 1.0)
        if not blended:
            return []

        merged = {}
        for word, value in blended.items():
            core = self._core(word)
            merged[core] = merged.get(core, 0.0) + value

        total = sum(merged.values())
        if not total:
            return []

        ranked = sorted(merged.items(), key=lambda item: (-item[1], item[0]))
        return [(word, value / total) for word, value in ranked[:max(1, int(limit))]]

    #------------------------------
    #Reporting
    #------------------------------

    def get_stats(self):
        states = sum(len(table) for table in self.models[1:])
        transitions = sum(
            sum(counter.values())
            for table in self.models[1:]
            for counter in table.values()
        )
        return {
            "orders": [size for size in range(1, self.order + 1) if self.models[size]],
            "total_transitions": transitions,
            "unique_states": states,
            "states_by_order": [
                len(self.models[size]) for size in range(1, self.order + 1)
            ],
            "total_words": self.total_words,
            "unique_words": len(self.word_counter),
            "sentences": self.sentences,
            "top_words": self.word_counter.most_common(8),
            "avg_sentence_words": (
                self.total_words / self.sentences if self.sentences else 0.0
            ),
        }
