"""Utility to create and save a trained Keras model for the TF analyzer.

Run this locally in a dev environment with TensorFlow installed to produce
model.json and weights.h5 under `analyzer_model/` so `TFAccountingAnalyzer`
can load a trained model.
"""

from __future__ import annotations

import os

# Get project root (parent of app/ directory)
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_DEFAULT_MODEL_DIR = os.path.join(_PROJECT_ROOT, "analyzer_model")


def _generate_synthetic_training_data(n_samples: int = 1000, seed: int = 42):
    """Generate synthetic financial data for training.

    Features: [revenue, expenses, net, cash, margin, ar_ap_ratio]
    Label: 1 = healthy, 0 = unhealthy
    """
    import numpy as np

    rng = np.random.RandomState(seed)

    # Generate healthy companies (positive cash, good margins)
    n_healthy = n_samples // 2
    healthy_revenue = rng.uniform(50000, 500000, n_healthy)
    healthy_margin = rng.uniform(0.15, 0.40, n_healthy)
    healthy_expenses = healthy_revenue * (1 - healthy_margin)
    healthy_net = healthy_revenue * healthy_margin
    healthy_cash = rng.uniform(10000, 100000, n_healthy)
    healthy_ar_ap = rng.uniform(0.5, 1.5, n_healthy)

    healthy = np.column_stack(
        [
            healthy_revenue,
            healthy_expenses,
            healthy_net,
            healthy_cash,
            healthy_margin,
            healthy_ar_ap,
        ]
    )
    healthy_labels = np.ones(n_healthy)

    # Generate unhealthy companies (negative cash, poor margins)
    n_unhealthy = n_samples - n_healthy
    unhealthy_revenue = rng.uniform(10000, 200000, n_unhealthy)
    unhealthy_margin = rng.uniform(-0.20, 0.05, n_unhealthy)
    unhealthy_expenses = unhealthy_revenue * (1 - unhealthy_margin)
    unhealthy_net = unhealthy_revenue * unhealthy_margin
    unhealthy_cash = rng.uniform(-50000, 5000, n_unhealthy)
    unhealthy_ar_ap = rng.uniform(2.0, 5.0, n_unhealthy)

    unhealthy = np.column_stack(
        [
            unhealthy_revenue,
            unhealthy_expenses,
            unhealthy_net,
            unhealthy_cash,
            unhealthy_margin,
            unhealthy_ar_ap,
        ]
    )
    unhealthy_labels = np.zeros(n_unhealthy)

    # Combine and shuffle
    X = np.vstack([healthy, unhealthy])  # noqa: N806
    y = np.concatenate([healthy_labels, unhealthy_labels])  # noqa: N806
    shuffle_idx = rng.permutation(n_samples)
    return X[shuffle_idx], y[shuffle_idx]


def _normalize_features(features):  # noqa: N803
    """Simple feature normalization for training stability."""
    import numpy as np

    # Log-scale large monetary values, clip outliers
    features_norm = features.copy()  # noqa: N806
    # Revenue, expenses, net, cash - log scale (add 1 to handle zeros/negatives)
    for i in [0, 1, 2, 3]:
        features_norm[:, i] = np.log1p(np.abs(features[:, i])) * np.sign(features[:, i] + 1e-6)
    # Margin and AR/AP are already reasonable scales
    return features_norm


def create_and_save_trained_model(output_dir: str | None = None) -> bool:
    """Create and train a working financial health classifier."""
    output_dir = output_dir or _DEFAULT_MODEL_DIR
    os.makedirs(output_dir, exist_ok=True)
    try:
        import numpy as np  # noqa: F401
        from tensorflow import keras
        from tensorflow.keras import layers
    except Exception as e:
        print("TensorFlow/NumPy not available:", e)
        return False

    # Generate and normalize training data
    X, y = _generate_synthetic_training_data(n_samples=2000)  # noqa: N806
    X_norm = _normalize_features(X)  # noqa: N806

    # Split train/val
    split = int(0.8 * len(X_norm))
    X_train, X_val = X_norm[:split], X_norm[split:]  # noqa: N806
    y_train, y_val = y[:split], y[split:]  # noqa: N806

    # Build model
    model = keras.Sequential(
        [
            layers.Input(shape=(6,)),
            layers.Dense(32, activation="relu"),
            layers.Dropout(0.2),
            layers.Dense(16, activation="relu"),
            layers.Dense(8, activation="relu"),
            layers.Dense(1, activation="sigmoid"),
        ]
    )
    model.compile(
        optimizer=keras.optimizers.Adam(learning_rate=0.001),
        loss="binary_crossentropy",
        metrics=["accuracy"],
    )

    # Train
    print("Training financial health classifier...")
    model.fit(
        X_train,
        y_train,
        validation_data=(X_val, y_val),
        epochs=30,
        batch_size=32,
        verbose=0,
    )

    # Evaluate
    loss, acc = model.evaluate(X_val, y_val, verbose=0)
    print(f"Validation accuracy: {acc:.3f}")

    # Save
    model_path = os.path.join(output_dir, "model.json")
    weights_path = os.path.join(output_dir, "weights.h5")

    with open(model_path, "w") as f:
        f.write(model.to_json())
    model.save_weights(weights_path)

    print(f"Saved trained model to {model_path} and weights to {weights_path}")
    return True


def create_and_save_model(output_dir: str | None = None) -> bool:
    """Create and save a trained financial health classifier.

    This is the main entry point - creates and trains a model on synthetic
    financial data if no pre-trained model exists.
    """
    output_dir = output_dir or _DEFAULT_MODEL_DIR
    return create_and_save_trained_model(output_dir)


if __name__ == "__main__":
    create_and_save_trained_model()
