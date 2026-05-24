# biometric-sdk (Python)

SDK officiel pour l'API Biometric Recognition System.

## Installation

```bash
pip install biometric-sdk
# ou depuis le repo
pip install -e sdks/python
```

## Quickstart

```python
from biometric_sdk import BiometricClient

client = BiometricClient(
    api_url="https://api.biometric.example.com",
    api_key="bio_xxxxxxxxxxxxxxxxxxxxxxxx",   # ou bearer_token=…
)

# Reconnaissance
resp = client.recognize_from_file("photo.jpg", check_liveness=True)
for m in resp.matches:
    print(m.full_name, m.similarity)

# Contrôle d'accès
decision = client.check_access(
    "photo.jpg", zone_code="server_room", access_point="door_b1",
)
print(decision.decision, decision.reason)

# KYC
session = client.start_kyc("passport")
verdict = client.submit_kyc(session["session_token"], "selfie.jpg", "passport.jpg")
print(verdict.decision, verdict.confidence)

client.close()
```

## Async

```python
import asyncio
from biometric_sdk import AsyncBiometricClient

async def main():
    async with AsyncBiometricClient(api_url="...", api_key="...") as client:
        resp = await client.recognize_from_file("photo.jpg")
        print(resp)

asyncio.run(main())
```

## Webhooks — vérification de signature

```python
from biometric_sdk import verify_webhook_signature

# Côté serveur (Flask, FastAPI, Django…)
body = request.body  # raw text
sig = request.headers["X-Bio-Signature"]
if not verify_webhook_signature(WEBHOOK_SECRET, body, sig):
    return 401
```

## Gestion d'erreurs

```python
from biometric_sdk import AuthenticationError, RateLimitError, ApiError

try:
    client.recognize_from_file("photo.jpg")
except AuthenticationError:
    ...
except RateLimitError:
    ...   # quota tenant dépassé
except ApiError as e:
    print(e.status, e.detail)
```
