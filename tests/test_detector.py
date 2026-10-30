from pathlib import Path
import sys

import numpy as np
import pytest
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from detector import Detector, Autoencoder


def normal_rows():
    rng = np.random.default_rng(8)
    rps = rng.uniform(8, 24, 100)
    return np.column_stack([rps, rng.uniform(80, 95, 100), np.zeros(100), rng.uniform(65, 80, 100), rng.integers(1, 4, 100), rps * 250])


def test_trained_neural_model_separates_large_shift_and_survives_reload(tmp_path):
    detector = Detector(tmp_path)
    metadata = detector.fit(normal_rows())
    assert isinstance(detector.model, torch.nn.Module)
    assert metadata['train_windows'] == 75
    assert metadata['validation_windows'] == 25
    normal = detector.predict([15, 87, 0, 72, 2, 3750])
    overload = detector.predict([95, 170, 0.5, 140, 20, 20000])
    assert overload['anomaly']
    assert overload['score'] > normal['score'] * 5
    restored = Detector(tmp_path)
    assert restored.load()
    assert restored.predict([95, 170, 0.5, 140, 20, 20000])['score'] == pytest.approx(overload['score'])
    assert sum(c['share'] for c in overload['contributions']) == pytest.approx(1)


def test_rejects_insufficient_training_and_invalid_features(tmp_path):
    detector = Detector(tmp_path)
    with pytest.raises(ValueError):
        detector.fit(normal_rows()[:10])
    detector.fit(normal_rows())
    with pytest.raises(ValueError):
        detector.predict([float('nan')] * 6)
    with pytest.raises(ValueError):
        detector.predict([-1] * 6)
    with pytest.raises(ValueError):
        detector.predict([1] * 7)
