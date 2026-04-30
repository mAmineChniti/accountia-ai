"""Utility to create and save a tiny Keras model for the TF analyzer.

Run this locally in a dev environment with TensorFlow installed to produce
/model.json and /weights.h5 under `/app/.cache/tf_analyzer/` so `TFAccountingAnalyzer`
can load a trained model.
"""

from __future__ import annotations

import os


def create_and_save_dummy_model(output_dir: str | None = None) -> bool:
    output_dir = output_dir or "/app/.cache/tf_analyzer"
    os.makedirs(output_dir, exist_ok=True)
    try:
        from tensorflow import keras
        from tensorflow.keras import layers
    except Exception as e:
        print("TensorFlow not available:", e)
        return False

    # Tiny model: a few dense layers over numeric features
    model = keras.Sequential(
        [
            layers.Input(shape=(6,)),
            layers.Dense(16, activation="relu"),
            layers.Dense(8, activation="relu"),
            layers.Dense(1, activation="sigmoid"),
        ]
    )
    model.compile(optimizer="adam", loss="binary_crossentropy")

    # Save model architecture and weights in the format expected by TFAccountingAnalyzer
    model_json = model.to_json()
    model_path = os.path.join(output_dir, "model.json")
    weights_path = os.path.join(output_dir, "weights.h5")

    with open(model_path, "w") as f:
        f.write(model_json)

    model.save_weights(weights_path)

    print(f"Saved dummy model to {model_path} and weights to {weights_path}")
    return True


if __name__ == "__main__":
    create_and_save_dummy_model()
