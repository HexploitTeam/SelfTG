"""Standalone GRU text model; nothing under Com/ imports it."""
import os
import json
import numpy as np
import tensorflow as tf
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import Embedding, GRU, Dense, Dropout
from tensorflow.keras.preprocessing.text import Tokenizer
from tensorflow.keras.preprocessing.sequence import pad_sequences
from tensorflow.keras.callbacks import EarlyStopping, Callback

os.environ["CUDA_VISIBLE_DEVICES"] = "-1"
os.environ["TF_ENABLE_ONEDNN_OPTS"] = "0"
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "2"

MODEL_DIR = "ML/models"
os.makedirs(MODEL_DIR, exist_ok=True)

class ProgressCallback(Callback):
    def __init__(self, callback):
        super().__init__()
        self.callback = callback

    def on_epoch_end(self, epoch, logs=None):
        if self.callback:
            self.callback(epoch + 1, logs)

def load_tokenizer():
    path = os.path.join(MODEL_DIR, "tokenizer.json")
    if not os.path.exists(path):
        return None
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    tokenizer = Tokenizer(num_words=3000)  # cap vocabulary
    tokenizer.word_index = data['word_index']
    tokenizer.word_counts = data['word_counts']
    tokenizer.document_count = data['document_count']
    return tokenizer

def save_tokenizer(tokenizer):
    path = os.path.join(MODEL_DIR, "tokenizer.json")
    with open(path, 'w', encoding='utf-8') as f:
        json.dump({
            'word_index': tokenizer.word_index,
            'word_counts': tokenizer.word_counts,
            'document_count': tokenizer.document_count
        }, f)

#------------------------------
#Model
#------------------------------

def build_model(vocab_size, embedding_dim=32, gru_units=32):
    model = Sequential([
        Embedding(vocab_size, embedding_dim, input_length=None),
        GRU(gru_units, return_sequences=True),
        Dropout(0.2),
        GRU(gru_units),
        Dropout(0.2),
        Dense(vocab_size, activation='softmax')
    ])
    model.compile(loss='categorical_crossentropy', optimizer='adam', metrics=['accuracy'])
    return model

def sequence_generator(texts, tokenizer, vocab_size, max_len, batch_size=8):
    """Yield batches one by one, never storing all sequences."""
    sequences = []
    targets = []
    for text in texts:
        seq = tokenizer.texts_to_sequences([text])[0]
        for i in range(1, len(seq)):
            sequences.append(seq[:i])
            targets.append(seq[i])
            if len(sequences) >= batch_size:
                X = pad_sequences(sequences, maxlen=max_len)
                y = np.eye(vocab_size)[targets]
                yield X, y
                sequences = []
                targets = []
    if sequences:
        X = pad_sequences(sequences, maxlen=max_len)
        y = np.eye(vocab_size)[targets]
        yield X, y

#------------------------------
#Training
#------------------------------

def train_model(texts, epochs=15, batch_size=8, max_sequences=1000, progress_callback=None, verbose=1):
    if not texts:
        raise ValueError("No texts to train on.")
    # Cap the corpus before tokenizing; full histories exceed the Repl's memory
    if len(texts) > max_sequences:
        texts = texts[:max_sequences]

    # Keep only common words (3000)
    tokenizer = Tokenizer(num_words=3000, oov_token='<OOV>')
    tokenizer.fit_on_texts(texts)
    vocab_size = min(3000, len(tokenizer.word_index) + 1)
    save_tokenizer(tokenizer)

    # Determine max sequence length (cap at 30 to reduce complexity)
    max_len = 0
    for text in texts:
        seq = tokenizer.texts_to_sequences([text])[0]
        if len(seq) > max_len:
            max_len = len(seq)
    max_len = min(max_len, 30)

    model = build_model(vocab_size)

    callbacks = []
    if progress_callback:
        callbacks.append(ProgressCallback(progress_callback))
    callbacks.append(EarlyStopping(monitor='loss', patience=3, restore_best_weights=True))

    # Calculate steps per epoch (approximate)
    total_sequences = sum(max(1, len(tokenizer.texts_to_sequences([t])[0]) - 1) for t in texts)
    steps_per_epoch = max(1, total_sequences // batch_size)

    model.fit(
        sequence_generator(texts, tokenizer, vocab_size, max_len, batch_size),
        epochs=epochs,
        steps_per_epoch=steps_per_epoch,
        callbacks=callbacks,
        verbose=verbose
    )

    model.save(os.path.join(MODEL_DIR, "model.h5"))
    with open(os.path.join(MODEL_DIR, "max_len.txt"), 'w') as f:
        f.write(str(max_len))

    return model, tokenizer, max_len

#------------------------------
#Generation
#------------------------------

def generate_text(seed, model, tokenizer, max_len, num_words=20, temperature=0.9, repetition_penalty=1.3):
    seq = tokenizer.texts_to_sequences([seed])[0]
    for _ in range(num_words):
        padded = pad_sequences([seq], maxlen=max_len, padding='pre')
        pred = model.predict(padded, verbose=0)[0]
        # Repetition penalty
        for i, word_idx in enumerate(seq):
            if word_idx > 0:
                pred[word_idx] /= repetition_penalty
        # Temperature sampling
        preds = np.log(pred + 1e-10) / temperature
        exp_preds = np.exp(preds)
        preds = exp_preds / np.sum(exp_preds)
        next_word_idx = np.random.multinomial(1, preds, 1).argmax()
        if next_word_idx == 0:
            break
        seq.append(next_word_idx)
    result_words = []
    for idx in seq:
        for word, i in tokenizer.word_index.items():
            if i == idx:
                result_words.append(word)
                break
    return ' '.join(result_words)

def is_trained():
    return os.path.exists(os.path.join(MODEL_DIR, "model.h5"))