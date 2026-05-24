"""
Locust load test — biometric API.

Lance:
    pip install locust
    cd tests/load
    locust -f locustfile.py --host http://localhost:8000

UI: http://localhost:8089

Scénarios:
    - 20% login (register/login) → obtention JWT
    - 60% recognition (image base64) sur cycle d'identités enrôlées
    - 15% access check
    -  5% admin (stats, listes)
"""
from __future__ import annotations

import base64
import random
import secrets
import time
from pathlib import Path

from locust import HttpUser, task, between, events
from loguru import logger


# Chargement d'une image de test (placée dans tests/load/fixtures/face.jpg).
_FIXTURE = Path(__file__).parent / "fixtures" / "face.jpg"
_FACE_B64 = None
if _FIXTURE.exists():
    _FACE_B64 = "data:image/jpeg;base64," + base64.b64encode(_FIXTURE.read_bytes()).decode()
else:
    logger.warning(f"Pas de fixture {_FIXTURE} — recognition tasks désactivées")


class BiometricUser(HttpUser):
    wait_time = between(0.5, 2.0)

    access_token: str | None = None
    role: str | None = None

    def on_start(self):
        """Crée un compte unique par utilisateur Locust et se connecte."""
        email = f"locust-{secrets.token_hex(6)}@test.local"
        password = "TestPassword123!"
        r = self.client.post("/api/v1/auth/register", json={
            "email": email, "password": password, "full_name": "Locust User",
        }, name="POST /auth/register")
        if r.status_code in (200, 201):
            data = r.json()
            self.access_token = data["access_token"]
            self.role = data["role"]
        else:
            # Si l'inscription est désactivée, tente login (compte seed)
            r2 = self.client.post("/api/v1/auth/login", json={
                "email": "admin@local", "password": "changeMe123!",
            }, name="POST /auth/login")
            if r2.ok:
                d2 = r2.json()
                self.access_token = d2["access_token"]
                self.role = d2["role"]

    @property
    def headers(self) -> dict:
        return {"Authorization": f"Bearer {self.access_token}"} if self.access_token else {}

    # --------- Tasks ---------

    @task(20)
    def stats(self):
        self.client.get("/api/v1/stats", headers=self.headers, name="GET /stats")

    @task(60)
    def recognize(self):
        if not _FACE_B64:
            return
        self.client.post(
            "/api/v1/recognize",
            json={"image_base64": _FACE_B64, "check_liveness": False},
            headers=self.headers, name="POST /recognize",
        )

    @task(15)
    def access_check(self):
        if not _FACE_B64:
            return
        self.client.post(
            "/api/v1/access/check",
            json={
                "image_base64": _FACE_B64,
                "zone_code":    "lobby",
                "access_point": "load_test_door",
                "check_liveness": False,
            },
            headers=self.headers, name="POST /access/check",
        )

    @task(5)
    def list_identities(self):
        self.client.get("/api/v1/identities?limit=50",
                        headers=self.headers, name="GET /identities")


@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    logger.info(f"Démarrage load test contre {environment.host}")


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    s = environment.stats.total
    logger.info(
        f"Terminé: {s.num_requests} req, {s.num_failures} échecs, "
        f"p95={s.get_response_time_percentile(0.95):.0f}ms, "
        f"rps={s.current_rps:.1f}"
    )
