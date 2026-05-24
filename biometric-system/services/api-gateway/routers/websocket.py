"""
WebSocket — Flux temps réel
Connexion depuis webcam / frontend → reconnaissance continue
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../ai-core"))

import asyncio
import base64
import json
import time
import cv2
import numpy as np
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from loguru import logger

from auth.dependencies import authenticate_websocket

router = APIRouter(tags=["WebSocket temps réel"])


class ConnectionManager:
    """Gère les connexions WebSocket actives"""

    def __init__(self):
        self.active: dict[str, WebSocket] = {}

    async def connect(self, ws: WebSocket, client_id: str):
        await ws.accept()
        self.active[client_id] = ws
        logger.info(f"WS connecté: {client_id} | Total: {len(self.active)}")

    def disconnect(self, client_id: str):
        self.active.pop(client_id, None)
        logger.info(f"WS déconnecté: {client_id}")

    async def send(self, client_id: str, data: dict):
        ws = self.active.get(client_id)
        if ws:
            await ws.send_json(data)

    async def broadcast(self, data: dict):
        for ws in list(self.active.values()):
            try:
                await ws.send_json(data)
            except Exception:
                pass


manager = ConnectionManager()


@router.websocket("/ws/camera/{camera_id}")
async def camera_stream(websocket: WebSocket, camera_id: str):
    """
    WebSocket pour flux caméra temps réel.

    Authentification: passer le JWT en query param `?token=...`
    ou header `Authorization: Bearer <token>`.

    Protocol:
      Client → Server: {"type": "frame", "data": "<base64_image>", "liveness": true}
      Server → Client: {"type": "result", "event_type": "...", "matches": [...], ...}
      Server → Client: {"type": "error", "message": "..."}
      Server → Client: {"type": "ping"}
    """
    user = await authenticate_websocket(websocket)
    if user is None:
        return  # close() déjà appelé par authenticate_websocket

    await manager.connect(websocket, camera_id)
    logger.info(f"WS caméra {camera_id} authentifiée user={user.user_id} role={user.role}")

    from pipeline import get_pipeline
    pipeline = get_pipeline()

    frame_count = 0
    last_ping = time.time()

    try:
        while True:
            # Ping keepalive toutes les 30s
            if time.time() - last_ping > 30:
                await websocket.send_json({"type": "ping"})
                last_ping = time.time()

            try:
                raw = await asyncio.wait_for(
                    websocket.receive_text(), timeout=35.0
                )
            except asyncio.TimeoutError:
                continue

            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "message": "JSON invalide"})
                continue

            msg_type = msg.get("type", "frame")

            # ---- Traitement de frame ----
            if msg_type == "frame":
                b64_data = msg.get("data", "")
                check_liveness = msg.get("liveness", True)

                if not b64_data:
                    continue

                frame_count += 1
                t0 = time.perf_counter()

                try:
                    result = await pipeline.process_base64(
                        b64_data, check_liveness=check_liveness
                    )

                    event_type = "rejected"
                    if result.success:
                        if not result.is_live:
                            event_type = "spoof_detected"
                        elif result.matches:
                            event_type = "recognized"
                        elif result.face_count > 0:
                            event_type = "unknown"

                    response = {
                        "type":            "result",
                        "frame_id":        frame_count,
                        "event_type":      event_type,
                        "face_count":      result.face_count,
                        "is_live":         result.is_live,
                        "liveness_score":  result.liveness_score,
                        "quality_score":   result.quality_score,
                        "processing_ms":   result.processing_ms,
                        "matches": [
                            {
                                "identity_id": m.identity_id,
                                "full_name":   m.full_name,
                                "role":        m.role,
                                "similarity":  round(m.similarity, 3),
                            }
                            for m in result.matches
                        ],
                        "unknown_id":      result.unknown_ids[0] if result.unknown_ids else None,
                        "error":           result.error,
                    }
                    await websocket.send_json(response)

                    # Log event si visage reconnu ou inconnu
                    if result.face_count > 0 and result.success:
                        asyncio.create_task(
                            _log_ws_event(result, event_type, camera_id)
                        )

                except Exception as e:
                    logger.error(f"WS pipeline error: {e}")
                    await websocket.send_json({
                        "type": "error",
                        "message": str(e)
                    })

            # ---- Commandes de contrôle ----
            elif msg_type == "pong":
                pass  # Keepalive reçu

            elif msg_type == "config":
                # Mise à jour de config en direct
                threshold = msg.get("threshold")
                if threshold and 0.3 <= threshold <= 0.95:
                    pipeline.similarity_threshold = threshold
                    await websocket.send_json({
                        "type": "config_updated",
                        "threshold": threshold
                    })

    except WebSocketDisconnect:
        manager.disconnect(camera_id)
    except Exception as e:
        logger.error(f"WS erreur inattendue [{camera_id}]: {e}")
        manager.disconnect(camera_id)


async def _log_ws_event(result, event_type: str, camera_id: str):
    """Log async de l'événement en arrière-plan"""
    try:
        from database.supabase_client import log_recognition_event
        await log_recognition_event({
            "event_type":     event_type,
            "confidence":     result.matches[0].similarity if result.matches else None,
            "liveness_score": result.liveness_score,
            "camera_id":      camera_id,
            "identity_id":    result.matches[0].identity_id if result.matches else None,
        })
    except Exception as e:
        logger.warning(f"WS log event échoué: {e}")


@router.websocket("/ws/dashboard")
async def dashboard_feed(websocket: WebSocket):
    """
    WebSocket dashboard — reçoit les alertes temps réel.
    Réservé aux admins (JWT requis).
    """
    user = await authenticate_websocket(websocket)
    if user is None:
        return
    if user.role not in ("admin", "operator"):
        await websocket.close(code=1008, reason="Rôle insuffisant")
        return

    client_id = f"dashboard:{user.user_id}"
    await manager.connect(websocket, client_id)
    try:
        while True:
            await asyncio.sleep(30)
            await websocket.send_json({"type": "heartbeat"})
    except WebSocketDisconnect:
        manager.disconnect(client_id)
