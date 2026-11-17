# ML/lstm_model.py
import os
import json
import numpy as np
import random
import tensorflow as tf
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import Embedding, LSTM, Dense, Dropout
from tensorflow.keras.preprocessing.text import Tokenizer
from tensorflow.keras.preprocessing.sequence import pad_sequences
from tensorflow.keras.callbacks import EarlyStopping, Callback

os.environ["CUDA_VISIBLE_DEVICES"] = "-1"
os.environ["TF_ENABLE_ONEDNN_OPTS"] = "0"

MODEL_DIR = "ML/models"
os.makedirs(MODEL_DIR, exist_ok=True)

class ProgressCallback(Callback):
    """Custom callback to report progress after each epoch."""
    def __init__(self, callback, verbose=1):
        super().__init__()
        self.callback = callback
        self.verbose = verbose

    def on_epoch_end(self, epoch, logs=None):
        if self.callback:
            self.callback(epoch + 1, logs)

def load_tokenizer():
    path = os.path.join(MODEL_DIR, "tokenizer.json")
    if not os.path.exists(path):
        return None
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    tokenizer = Tokenizer()
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

def build_model(vocab_size, embedding_dim=48, lstm_units=48):
    model = Sequential([
        Embedding(vocab_size, embedding_dim, input_length=None),
        LSTM(lstm_units, return_sequences=True),
        Dropout(0.2),
        LSTM(lstm_units),
        Dropout(0.2),
        Dense(vocab_size, activation='softmax')
    ])
    model.compile(loss='categorical_crossentropy', optimizer='adam', metrics=['accuracy'])
    return model

def sequence_generator(texts, tokenizer, vocab_size, max_len, batch_size=16):
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

def train_model(texts, epochs=12, batch_size=16, max_sequences=2000, progress_callback=None, verbose=1):
    if not texts:
        raise ValueError("No texts to train on.")
    if len(texts) > max_sequences:
        texts = texts[:max_sequences]

    tokenizer = Tokenizer()
    tokenizer.fit_on_texts(texts)
    vocab_size = len(tokenizer.word_index) + 1
    save_tokenizer(tokenizer)

    model = build_model(vocab_size)

    max_len = 0
    for text in texts:
        seq = tokenizer.texts_to_sequences([text])[0]
        if len(seq) > max_len:
            max_len = len(seq)
    max_len = min(max_len, 50)

    steps = len(texts) * 10 // batch_size
    callbacks = [EarlyStopping(monitor='loss', patience=3, restore_best_weights=True)]
    if progress_callback:
        callbacks.append(ProgressCallback(progress_callback, verbose=verbose))

    model.fit(
        sequence_generator(texts, tokenizer, vocab_size, max_len, batch_size),
        epochs=epochs,
        steps_per_epoch=steps,
        callbacks=callbacks,
        verbose=verbose
    )

    model.save(os.path.join(MODEL_DIR, "model.h5"))
    with open(os.path.join(MODEL_DIR, "max_len.txt"), 'w') as f:
        f.write(str(max_len))

    return model, tokenizer, max_len

def sample_with_temperature(preds, temperature=0.8):
    preds = np.asarray(preds).astype('float64')
    preds = np.log(preds + 1e-10) / temperature
    exp_preds = np.exp(preds)
    preds = exp_preds / np.sum(exp_preds)
    probas = np.random.multinomial(1, preds, 1)
    return np.argmax(probas)

def generate_text(seed, model, tokenizer, max_len, num_words=20, temperature=0.9, repetition_penalty=1.3):
    seq = tokenizer.texts_to_sequences([seed])[0]
    for _ in range(num_words):
        padded = pad_sequences([seq], maxlen=max_len, padding='pre')
        pred = model.predict(padded, verbose=0)[0]
        for i, word_idx in enumerate(seq):
            if word_idx > 0:
                pred[word_idx] /= repetition_penalty
        next_word_idx = sample_with_temperature(pred, temperature)
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