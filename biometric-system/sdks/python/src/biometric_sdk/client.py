"""
Client SDK — wrapper httpx avec auth tenant (API key) ou user (Bearer JWT).
"""
from __future__ import annotations

import base64
from pathlib import Path
from typing import Optional, Union

import httpx

from biometric_sdk.exceptions import (
    AuthenticationError, RateLimitError, ApiError,
)
from biometric_sdk.models import (
    RecognizeResponse, AccessCheckResponse, KYCResponse,
)


_DEFAULT_TIMEOUT = 30.0


class _BaseClient:
    def __init__(
        self,
        api_url: str,
        api_key: Optional[str] = None,
        bearer_token: Optional[str] = None,
        tenant_id: Optional[str] = None,
        timeout: float = _DEFAULT_TIMEOUT,
    ):
        if not api_key and not bearer_token:
            raise ValueError("Fournir api_key ou bearer_token")
        self.api_url = api_url.rstrip("/")
        self.timeout = timeout
        self._headers = {"User-Agent": "biometric-sdk-python/1.0"}
        if api_key:
            self._headers["X-API-Key"] = api_key
        if bearer_token:
            self._headers["Authorization"] = f"Bearer {bearer_token}"
        if tenant_id:
            self._headers["X-Tenant-Id"] = tenant_id

    @staticmethod
    def _file_to_data_url(path: Union[str, Path], mime: str = "image/jpeg") -> str:
        data = Path(path).read_bytes()
        return f"data:{mime};base64," + base64.b64encode(data).decode()

    @staticmethod
    def _raise_for(r: httpx.Response) -> None:
        if r.status_code == 401:
            raise AuthenticationError(r.text)
        if r.status_code == 429:
            raise RateLimitError(r.text)
        if r.status_code >= 400:
            try:
                detail = r.json().get("detail", r.text)
            except Exception:
                detail = r.text
            raise ApiError(r.status_code, detail)


# ============================================================
# Synchronous client
# ============================================================

class BiometricClient(_BaseClient):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._http = httpx.Client(
            base_url=self.api_url, headers=self._headers, timeout=self.timeout,
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self):  return self
    def __exit__(self, *a):  self.close()

    # ----- Reconnaissance -----
    def recognize_from_file(self, path: Union[str, Path], check_liveness: bool = True) -> RecognizeResponse:
        r = self._http.post("/api/v1/recognize", json={
            "image_base64": self._file_to_data_url(path),
            "check_liveness": check_liveness,
        })
        self._raise_for(r)
        return RecognizeResponse.from_dict(r.json())

    def recognize_from_base64(self, b64: str, check_liveness: bool = True) -> RecognizeResponse:
        r = self._http.post("/api/v1/recognize", json={
            "image_base64": b64, "check_liveness": check_liveness,
        })
        self._raise_for(r)
        return RecognizeResponse.from_dict(r.json())

    # ----- Accès -----
    def check_access(
        self, image_path: Union[str, Path], zone_code: str,
        access_point: str, check_liveness: bool = True,
    ) -> AccessCheckResponse:
        r = self._http.post("/api/v1/access/check", json={
            "image_base64": self._file_to_data_url(image_path),
            "zone_code": zone_code, "access_point": access_point,
            "check_liveness": check_liveness,
        })
        self._raise_for(r)
        return AccessCheckResponse.from_dict(r.json())

    # ----- KYC -----
    def start_kyc(self, doc_type: str, issue_challenge: bool = True) -> dict:
        r = self._http.post("/api/v1/kyc/sessions", json={
            "doc_type": doc_type, "issue_challenge": issue_challenge,
        })
        self._raise_for(r)
        return r.json()

    def submit_kyc(
        self, session_token: str, selfie: Union[str, Path], document: Union[str, Path],
    ) -> KYCResponse:
        r = self._http.post("/api/v1/kyc/sessions/submit", json={
            "session_token": session_token,
            "selfie_base64":   self._file_to_data_url(selfie),
            "document_base64": self._file_to_data_url(document),
        })
        self._raise_for(r)
        return KYCResponse.from_dict(r.json())

    # ----- Identités -----
    def list_identities(self, limit: int = 50) -> list[dict]:
        r = self._http.get(f"/api/v1/identities?limit={limit}")
        self._raise_for(r)
        return r.json().get("items", [])

    def create_identity(self, full_name: str, **kwargs) -> dict:
        payload = {"full_name": full_name, **kwargs}
        r = self._http.post("/api/v1/identities", json=payload)
        self._raise_for(r)
        return r.json()

    def enroll_face(self, identity_id: str, image_path: Union[str, Path]) -> dict:
        with open(image_path, "rb") as f:
            files = {"file": (Path(image_path).name, f, "image/jpeg")}
            r = self._http.post(
                f"/api/v1/identities/{identity_id}/enroll/upload", files=files,
            )
        self._raise_for(r)
        return r.json()


# ============================================================
# Async client
# ============================================================

class AsyncBiometricClient(_BaseClient):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._http = httpx.AsyncClient(
            base_url=self.api_url, headers=self._headers, timeout=self.timeout,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self):  return self
    async def __aexit__(self, *a):  await self.aclose()

    async def recognize_from_file(self, path: Union[str, Path], check_liveness: bool = True) -> RecognizeResponse:
        r = await self._http.post("/api/v1/recognize", json={
            "image_base64": self._file_to_data_url(path),
            "check_liveness": check_liveness,
        })
        self._raise_for(r)
        return RecognizeResponse.from_dict(r.json())

    async def check_access(
        self, image_path: Union[str, Path], zone_code: str,
        access_point: str, check_liveness: bool = True,
    ) -> AccessCheckResponse:
        r = await self._http.post("/api/v1/access/check", json={
            "image_base64": self._file_to_data_url(image_path),
            "zone_code": zone_code, "access_point": access_point,
            "check_liveness": check_liveness,
        })
        self._raise_for(r)
        return AccessCheckResponse.from_dict(r.json())
