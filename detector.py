"""Vrai autoencodeur PyTorch. Ce module ignore les commandes du simulateur."""
from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import torch
from torch import nn

torch.set_num_threads(1)

FEATURES = ["Requêtes / s", "Latence p95 (ms)", "Taux d'erreur", "Latence moyenne (ms)", "Concurrence maximale", "Octets / s"]
ARCHITECTURE = [6, 12, 6, 2, 6, 12, 6]


class Autoencoder(nn.Module):
    def __init__(self):
        super().__init__()
        layers = []
        for i, (a, b) in enumerate(zip(ARCHITECTURE[:-1], ARCHITECTURE[1:])):
            layers.append(nn.Linear(a, b))
            if i < len(ARCHITECTURE) - 2:
                layers.append(nn.Tanh())
        self.network = nn.Sequential(*layers)

    def forward(self, x):
        return self.network(x)


class Detector:
    def __init__(self, directory: Path):
        self.directory = directory
        self.model = None
        self.mean = None
        self.scale = None
        self.threshold = None
        self.metadata = None

    @property
    def ready(self):
        return self.model is not None

    def fit(self, rows):
        """Chronological train/validation split; all inputs must be normal captures."""
        raw = np.asarray(rows, dtype=np.float32)
        if raw.ndim != 2 or raw.shape[1] != len(FEATURES) or len(raw) < 60:
            raise ValueError("Il faut au moins 60 fenêtres normales de six caractéristiques.")
        if not np.isfinite(raw).all() or (raw < 0).any():
            raise ValueError("Mesures invalides.")
        torch.manual_seed(42)
        split = int(len(raw) * 0.75)
        transformed = np.log1p(raw)
        mean = transformed[:split].mean(axis=0)
        # Floors avoid amplifying tiny changes in normally constant measurements.
        scale = np.maximum(transformed[:split].std(axis=0), [0.25, 0.20, 0.03, 0.20, 0.35, 0.30]).astype(np.float32)
        x = torch.tensor((transformed - mean) / scale, dtype=torch.float32)
        train, validation = x[:split], x[split:]
        model = Autoencoder()
        optimizer = torch.optim.Adam(model.parameters(), lr=0.005, weight_decay=0.0001)
        best, best_epoch, best_state = float("inf"), 0, None
        history = []
        for epoch in range(1, 301):
            model.train()
            optimizer.zero_grad()
            loss = (model(train) - train).square().mean()
            loss.backward()
            optimizer.step()
            model.eval()
            with torch.no_grad():
                val_loss = (model(validation) - validation).square().mean().item()
            history.append({"epoch": epoch, "train": round(loss.item(), 6), "validation": round(val_loss, 6)})
            if val_loss < best - 0.00001:
                best, best_epoch, best_state = val_loss, epoch, copy.deepcopy(model.state_dict())
            if epoch - best_epoch >= 45:
                break
        model.load_state_dict(best_state)
        model.eval()
        with torch.no_grad():
            val_scores = (model(validation) - validation).square().mean(dim=1).numpy()
        # Conservative teaching threshold, chosen without any attack samples.
        threshold = max(float(np.quantile(val_scores, 0.99)) * 2.5, 1.5)
        metadata = {
            "trained_at": datetime.now(timezone.utc).isoformat(),
            "framework": "PyTorch", "architecture": ARCHITECTURE,
            "parameters": sum(p.numel() for p in model.parameters()),
            "features": FEATURES, "train_windows": split,
            "validation_windows": len(raw) - split, "normal_windows": len(raw),
            "epochs": len(history), "best_epoch": best_epoch,
            "loss": "MSE de reconstruction après log1p et standardisation",
            "threshold": threshold,
            "threshold_rule": "max(2.5 × quantile 99 % des scores de validation normaux, 1.5)",
            "history": history,
            "scope": "Calibration locale de démonstration ; aucune garantie de généralisation à un réseau réel.",
        }
        self.directory.mkdir(parents=True, exist_ok=True)
        torch.save({"weights": best_state, "mean": mean.tolist(), "scale": scale.tolist(), "threshold": threshold}, self.directory / "autoencoder.pt")
        (self.directory / "model.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        np.savetxt(self.directory / "normal_windows.csv", raw, delimiter=",", header=",".join(FEATURES), comments="", encoding="utf-8")
        self.mean, self.scale, self.threshold, self.metadata = mean, scale, threshold, metadata
        self.model = model
        return metadata

    def load(self):
        path = self.directory / "autoencoder.pt"
        if not path.exists():
            return False
        data = torch.load(path, map_location="cpu", weights_only=True)
        model = Autoencoder()
        model.load_state_dict(data["weights"])
        model.eval()
        self.mean = np.array(data["mean"], dtype=np.float32)
        self.scale = np.array(data["scale"], dtype=np.float32)
        self.threshold = float(data["threshold"])
        self.metadata = json.loads((self.directory / "model.json").read_text(encoding="utf-8"))
        self.model = model
        return True

    def predict(self, measurements):
        if not self.ready:
            return None
        raw = np.asarray(measurements, dtype=np.float32)
        if raw.shape != (len(FEATURES),) or not np.isfinite(raw).all() or (raw < 0).any():
            raise ValueError("Six mesures positives et finies sont requises.")
        x = torch.tensor((np.log1p(raw) - self.mean) / self.scale)
        with torch.no_grad():
            errors = (self.model(x) - x).square().numpy()
        score = float(errors.mean())
        total = float(errors.sum())
        contributions = [{"name": FEATURES[i], "share": float(v / total) if total else 0} for i, v in enumerate(errors)]
        contributions.sort(key=lambda item: item["share"], reverse=True)
        return {"score": score, "ratio": score / self.threshold, "anomaly": score > self.threshold, "contributions": contributions}
