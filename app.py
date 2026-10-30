"""Sentinel Lab: local API, bounded HTTP load, neural detector, live dashboard."""
from __future__ import annotations

import asyncio
import contextlib
import csv
import io
import json
import os
import random
import secrets
import time
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import httpx
import numpy as np
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from detector import Detector, FEATURES

ROOT = Path(__file__).resolve().parent
PORT = int(os.environ.get("SENTINEL_PORT", "8765"))
TARGET = f"http://127.0.0.1:{PORT}/api/service"
CALIBRATION_WINDOWS = 90
MAX_SCENARIO_SECONDS = 25


class Lab:
    def __init__(self):
        self.detector = Detector(ROOT / "artifacts")
        self.error = None
        try:
            self.detector.load()
        except Exception as exc:
            self.error = f"Modèle à recalibrer : {exc}"
        self.token = secrets.token_urlsafe(24)
        self.windows = deque(maxlen=600)
        self.events = deque(maxlen=80)
        self.requests = deque(maxlen=60)
        self.completed = []
        self.active = self.peak = 0
        self.capacity = asyncio.Semaphore(3)
        self.pending = set()
        self.normal = True
        self.scenario = "normal"
        self.scenario_until = 0.0
        self.scenario_started = None
        self.scenario_detected = None
        self.consecutive = 0
        self.alert = False
        self.phase = "ready" if self.detector.ready else "untrained"
        self.calibration = []
        self.training_task = None
        self.warmup_until = 0.0
        self.total_requests = 0
        self.client_errors = 0
        self.started = time.monotonic()
        self.rng = random.Random(42)
        self.latest = None
        self.event("system", "Laboratoire démarré. Cible HTTP limitée à 127.0.0.1.")

    def event(self, kind, message):
        self.events.appendleft({"time": datetime.now(timezone.utc).isoformat(), "kind": kind, "message": message})

    async def serve(self):
        start = time.perf_counter()
        self.active += 1
        self.peak = max(self.peak, self.active)
        acquired = False
        try:
            try:
                await asyncio.wait_for(self.capacity.acquire(), timeout=0.10)
                acquired = True
                # Controlled I/O latency and bounded service capacity; no CPU flood.
                await asyncio.sleep(self.rng.uniform(0.055, 0.085))
                status = 200
                body = {"status": "ok", "service": "api-demo", "payload": "telemetrie-" * 20}
            except TimeoutError:
                status = 503
                body = {"status": "busy", "message": "Capacité du service de démonstration atteinte"}
            response = JSONResponse(body, status_code=status)
            elapsed = (time.perf_counter() - start) * 1000
            self.completed.append((elapsed, status, len(response.body)))
            self.total_requests += 1
            self.requests.appendleft({"time": datetime.now(timezone.utc).isoformat(), "status": status, "latency": round(elapsed, 1)})
            return response
        finally:
            self.active -= 1
            if acquired:
                self.capacity.release()

    async def generate(self):
        async with httpx.AsyncClient(timeout=2, trust_env=False, limits=httpx.Limits(max_connections=32, max_keepalive_connections=32)) as client:
            async def send():
                try:
                    await client.get(TARGET)
                except httpx.HTTPError:
                    self.client_errors += 1
            try:
                while True:
                    now = time.monotonic()
                    if self.scenario != "normal" and now >= self.scenario_until:
                        self.event("scenario", "Fin du scénario. Retour au trafic normal.")
                        self.scenario = "normal"
                    # These are generator settings, never detector inputs.
                    if self.scenario == "attack":
                        rate = 100
                    elif self.scenario == "legitimate":
                        rate = 24
                    elif self.normal:
                        rate = [8, 12, 18, 24, 14, 20][int((now - self.started) // 4) % 6]
                    else:
                        rate = 0
                    if rate and len(self.pending) < 28:
                        task = asyncio.create_task(send())
                        self.pending.add(task)
                        task.add_done_callback(self.pending.discard)
                    await asyncio.sleep(1 / rate if rate else 0.1)
            finally:
                for task in self.pending:
                    task.cancel()
                await asyncio.gather(*self.pending, return_exceptions=True)

    async def train(self, rows):
        self.phase = "training"
        self.event("model", "Entraînement PyTorch sur les fenêtres normales collectées.")
        try:
            await asyncio.to_thread(self.detector.fit, rows)
            self.phase = "ready"
            self.event("model", f"Autoencodeur entraîné : {self.detector.metadata['parameters']} paramètres. Seuil fixé sur la validation normale.")
        except Exception as exc:
            self.phase = "error"
            self.error = str(exc)
            self.event("error", f"Échec de l'entraînement : {exc}")

    async def monitor(self):
        (ROOT / "artifacts").mkdir(exist_ok=True)
        previous = time.monotonic()
        with (ROOT / "artifacts" / "session.csv").open("w", newline="", encoding="utf-8") as file:
            fields = ["timestamp", "rps", "p95_ms", "error_rate", "mean_ms", "peak_concurrency", "bytes_per_second", "score", "threshold", "alert", "scenario", "phase"]
            writer = csv.DictWriter(file, fieldnames=fields)
            writer.writeheader()
            while True:
                await asyncio.sleep(1)
                now = time.monotonic()
                dt, previous = now - previous, now
                done, self.completed = self.completed, []
                peak, self.peak = self.peak, self.active
                if done:
                    latency = [item[0] for item in done]
                    vector = [len(done) / dt, float(np.percentile(latency, 95)), sum(item[1] >= 400 for item in done) / len(done), float(np.mean(latency)), float(peak), sum(item[2] for item in done) / dt]
                else:
                    vector = [0.0] * 6
                if self.phase == "collecting" and now >= self.warmup_until and done:
                    self.calibration.append(vector)
                    if len(self.calibration) >= CALIBRATION_WINDOWS:
                        self.phase = "training"
                        self.training_task = asyncio.create_task(self.train(list(self.calibration)))
                prediction = self.detector.predict(vector) if self.phase == "ready" and done else None
                # Two consecutive abnormal windows confirm an alert; no scenario flag.
                anomalous = bool(prediction and prediction["anomaly"])
                self.consecutive = self.consecutive + 1 if anomalous else 0
                previous_alert = self.alert
                self.alert = self.consecutive >= 2
                timestamp = datetime.now(timezone.utc).isoformat()
                if self.alert and not previous_alert:
                    self.event("alert", "Anomalie confirmée sur deux fenêtres successives.")
                    # Ground truth is used only to evaluate observed detection latency.
                    if self.scenario == "attack" and self.scenario_detected is None:
                        self.scenario_detected = now - self.scenario_started
                if previous_alert and not anomalous:
                    self.event("recovery", "Score revenu sous le seuil.")
                point = {"timestamp": timestamp, "rps": round(vector[0], 2), "p95_ms": round(vector[1], 2), "error_rate": round(vector[2], 4), "mean_ms": round(vector[3], 2), "peak_concurrency": peak, "bytes_per_second": round(vector[5], 2), "score": prediction["score"] if prediction else None, "threshold": self.detector.threshold, "ratio": prediction["ratio"] if prediction else None, "alert": self.alert, "candidate": anomalous, "scenario": self.scenario, "phase": self.phase, "contributions": prediction["contributions"] if prediction else []}
                self.latest = point
                self.windows.append(point)
                writer.writerow({key: point[key] for key in fields})
                file.flush()

    def state(self):
        return {"phase": self.phase, "normal": self.normal, "scenario": self.scenario,
                "scenario_remaining": max(0, round(self.scenario_until - time.monotonic())) if self.scenario != "normal" else 0,
                "detection_seconds": round(self.scenario_detected, 2) if self.scenario_detected is not None else None,
                "calibration_count": len(self.calibration), "calibration_target": CALIBRATION_WINDOWS,
                "model": self.detector.metadata, "latest": self.latest,
                "history": list(self.windows)[-180:], "events": list(self.events)[:20], "requests": list(self.requests)[:12],
                "total_requests": self.total_requests, "client_errors": self.client_errors,
                "error": self.error, "token": self.token, "target": TARGET}


lab: Lab | None = None


@asynccontextmanager
async def lifespan(app):
    global lab
    lab = Lab()
    tasks = [asyncio.create_task(lab.generate()), asyncio.create_task(lab.monitor())]
    yield
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    if lab.training_task:
        await lab.training_task


app = FastAPI(title="Sentinel Lab — démonstration locale", lifespan=lifespan)


@app.middleware("http")
async def loopback_only(request: Request, call_next):
    # Localhost binding + Host check + same-origin token on mutations.
    allowed_hosts = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}
    if request.headers.get("host") not in allowed_hosts:
        return JSONResponse({"detail": "Accès local uniquement"}, status_code=403)
    if request.method == "POST":
        origin = request.headers.get("origin")
        if origin and origin not in {f"http://{h}" for h in allowed_hosts}:
            return JSONResponse({"detail": "Origine refusée"}, status_code=403)
        if not lab or request.headers.get("x-lab-token") != lab.token:
            return JSONResponse({"detail": "Jeton local requis"}, status_code=403)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'"
    return response


@app.get("/")
async def index():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/api/service")
async def service():
    return await lab.serve()


@app.get("/api/state")
async def state():
    return lab.state()


class Command(BaseModel):
    action: str


@app.post("/api/control")
async def control(command: Command):
    action = command.action
    busy = lab.phase in {"collecting", "training"}
    if action == "calibrate":
        if busy:
            raise HTTPException(409, "Calibration déjà en cours.")
        lab.scenario = "normal"
        lab.normal = True
        lab.phase = "collecting"
        lab.calibration = []
        lab.warmup_until = time.monotonic() + 3
        lab.consecutive = 0
        lab.alert = False
        lab.error = None
        lab.scenario_detected = None
        lab.event("model", "Collecte de 90 fenêtres normales réelles ; trois secondes de stabilisation.")
    elif action in {"attack", "legitimate"}:
        if busy or not lab.detector.ready:
            raise HTTPException(409, "Terminer la calibration avant les scénarios.")
        if lab.scenario != "normal":
            raise HTTPException(409, "Arrêter le scénario actuel avant d'en lancer un autre.")
        lab.normal = True
        lab.scenario = action
        lab.scenario_started = time.monotonic()
        lab.scenario_until = lab.scenario_started + MAX_SCENARIO_SECONDS
        lab.scenario_detected = None
        lab.event("scenario", "Surcharge contrôlée : cible fixe locale, consigne de 100 requêtes/s, durée 25 s." if action == "attack" else "Pic légitime : 24 requêtes/s pendant 25 s.")
    elif action == "stop":
        lab.scenario = "normal"
        lab.normal = False
        if lab.phase == "collecting":
            lab.phase = "ready" if lab.detector.ready else "untrained"
        lab.event("system", "Génération de trafic arrêtée ; les requêtes en cours se terminent.")
    elif action == "normal":
        if lab.phase == "training":
            raise HTTPException(409, "Entraînement en cours.")
        lab.normal = True
        lab.scenario = "normal"
        lab.event("scenario", "Trafic normal activé (8 à 24 requêtes/s).")
    else:
        raise HTTPException(400, "Commande inconnue.")
    return {"ok": True, "phase": lab.phase}


@app.get("/api/export")
async def export():
    # Snapshot the growing log: a streaming FileResponse can race its Content-Length.
    content = (ROOT / "artifacts" / "session.csv").read_bytes()
    return Response(content, media_type="text/csv; charset=utf-8", headers={"Content-Disposition": 'attachment; filename="sentinel-session.csv"'})


@app.get("/api/model")
async def model():
    if not lab.detector.ready:
        raise HTTPException(404, "Entraîner le modèle d'abord.")
    return JSONResponse(lab.detector.metadata)


app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


if __name__ == "__main__":
    print(f"Sentinel Lab : http://127.0.0.1:{PORT}", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning", access_log=False)
