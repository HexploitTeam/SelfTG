"""Variable-order Markov chain used by the !aiml commands for local text generation."""
import ast
import os
import json
import random
import re
from collections import defaultdict, Counter

MODEL_DIR = "ML/models"
os.makedirs(MODEL_DIR, exist_ok=True)

class SmartMarkov:
    def __init__(self, order=4):
        self.order = order
        self.transitions = defaultdict(list)
        self.start_words = []
        self.all_words = []
        self.word_counter = Counter()

    def train(self, texts):
        if not texts:
            return
        for text in texts:
            words = text.split()
            if len(words) < self.order + 1:
                continue
            if len(words) >= 2:
                self.start_words.append(' '.join(words[:2]))
            for i in range(len(words) - self.order):
                state = tuple(words[i:i+self.order])
                next_word = words[i+self.order]
                self.transitions[state].append(next_word)
            self.all_words.extend(words)
            for w in words:
                self.word_counter[w] += 1

    def generate(self, seed=None, max_words=30):
        if not self.transitions:
            return None

        if seed:
            seed_words = seed.split()
            # Prefer a state that begins with the seed so generation stays on topic
            for i in range(len(seed_words), 0, -1):
                prefix = tuple(seed_words[:i])
                for state in self.transitions.keys():
                    if state[:i] == prefix:
                        result = list(state)
                        # Then continue from there
                        for _ in range(max_words - len(result)):
                            next_words = self.transitions.get(tuple(result[-self.order:]))
                            if not next_words:
                                break
                            next_word = random.choice(next_words)
                            result.append(next_word)
                        return ' '.join(result)
            # If no state starts with seed, pick a random start
            # But we'll try to match the seed partially
            for i in range(len(seed_words), 0, -1):
                prefix = tuple(seed_words[:i])
                for state in self.transitions.keys():
                    if state[:i] == prefix:
                        result = list(state)
                        for _ in range(max_words - len(result)):
                            next_words = self.transitions.get(tuple(result[-self.order:]))
                            if not next_words:
                                break
                            next_word = random.choice(next_words)
                            result.append(next_word)
                        return ' '.join(result)

        # No seed or seed not found – start from a random state
        state = random.choice(list(self.transitions.keys()))
        result = list(state)
        for _ in range(max_words - len(result)):
            next_words = self.transitions.get(tuple(result[-self.order:]))
            if not next_words:
                break
            next_word = random.choice(next_words)
            result.append(next_word)

        return ' '.join(result)

    def save(self, filepath):
        data = {
            "order": self.order,
            "transitions": {str(k): v for k, v in self.transitions.items()},
            "start_words": self.start_words,
            "all_words": self.all_words,
            "word_counter": dict(self.word_counter)
        }
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        mc = cls(order=data["order"])
        # ast.literal_eval instead of eval: the model file is untrusted input and
        # eval() there allowed arbitrary code execution from a crafted model.
        transitions = defaultdict(list)
        for key, value in data["transitions"].items():
            try:
                transitions[ast.literal_eval(key)] = value
            except (ValueError, SyntaxError, TypeError):
                continue
        mc.transitions = transitions
        mc.start_words = data["start_words"]
        mc.all_words = data["all_words"]
        mc.word_counter = Counter(data["word_counter"])
        return mc

    def get_stats(self):
        return {
            "total_transitions": sum(len(v) for v in self.transitions.values()),
            "unique_states": len(self.transitions),
            "total_words": len(self.all_words),
            "unique_words": len(self.word_counter)
        }