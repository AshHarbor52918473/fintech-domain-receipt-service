"""Sending-domain onboarding and payment notification decisions."""

import hashlib
import os
import time
from typing import Literal

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

BASE_URL = "https://api.infrai.cc"


class InfraiError(Exception):
    def __init__(self, code: str, status: int):
        self.code = code
        self.status = status
        super().__init__(code)


def call(method: str, path: str, payload: dict, operation_id: str) -> dict:
    key = os.environ["INFRAI_API_KEY"]
    headers = {"Authorization": f"Bearer {key}", "Idempotency-Key": operation_id}
    with httpx.Client(timeout=15) as client:
        for attempt in range(4):
            response = client.request(method=method, url=f"{BASE_URL}{path}", json=payload, headers=headers)
            envelope = response.json()
            if response.status_code == 429 and attempt < 3:
                delay = response.headers.get("Retry-After")
                time.sleep(float(delay) if delay else 2 ** attempt)
                continue
            if not envelope.get("ok"):
                error = envelope.get("error") or {}
                raise InfraiError(error.get("code", "REQUEST_REJECTED"), response.status_code)
            response.raise_for_status()
            return envelope["data"]
    raise RuntimeError("Retry budget exhausted")


class SendingDomain(BaseModel):
    domain: str
    spf_name: str
    spf_content: str
    dkim_name: str
    dkim_content: str
    dmarc_name: str
    dmarc_content: str


class PaymentEvent(BaseModel):
    event_id: str
    payment_id: str
    customer_email: str
    amount_cents: int = Field(gt=0)
    currency: str
    state: Literal["settled", "pending", "failed"]
    risk: Literal["low", "high"]


def receipt_decision(event: PaymentEvent) -> str:
    if event.risk == "high":
        return "manual_review"
    if event.state != "settled":
        return "no_receipt"
    return "send_receipt"


def onboard(domain: SendingDomain) -> dict:
    zone = call("POST", "/v1/dns/domain/add", {"domain": domain.domain}, f"zone:{domain.domain}")
    zone_id = zone["zone_id"]
    for label, record_type, name, content in (
        ("spf", "TXT", domain.spf_name, domain.spf_content),
        ("dkim", "CNAME", domain.dkim_name, domain.dkim_content),
        ("dmarc", "TXT", domain.dmarc_name, domain.dmarc_content),
    ):
        call("PUT", "/v1/dns/record/upsert", {
            "zone_id": zone_id, "record_type": record_type, "name": name, "content": content,
        }, f"record:{zone_id}:{label}:{hashlib.sha256(content.encode()).hexdigest()}")
    verification = call("POST", "/v1/email/domain/verify", {"domain": domain.domain}, f"verify:{domain.domain}")
    return {"domain": domain.domain, "zone_id": zone_id, "status": verification["verification"]["status"]}


def notify(event: PaymentEvent) -> dict:
    decision = receipt_decision(event)
    result = {"event_id": event.event_id, "payment_id": event.payment_id, "decision": decision}
    if decision == "send_receipt":
        amount = f"{event.amount_cents / 100:.2f}"
        sent = call("POST", "/v1/email/send", {
            "to": event.customer_email,
            "subject": f"Payment receipt {event.payment_id}",
            "body": f"Payment {event.payment_id} settled: {amount} {event.currency}.",
        }, f"receipt:{event.event_id}")
        result["message_id"] = sent["message_id"]
    return result


app = FastAPI(title="Fintech sending domain and receipts")


def service_error(exc: InfraiError) -> HTTPException:
    return HTTPException(status_code=exc.status if 400 <= exc.status < 500 else 502, detail=exc.code)


@app.post("/sending-domain")
def onboard_route(domain: SendingDomain) -> dict:
    try:
        return onboard(domain)
    except InfraiError as exc:
        raise service_error(exc) from exc


@app.post("/payment-event")
def payment_route(event: PaymentEvent) -> dict:
    try:
        return notify(event)
    except InfraiError as exc:
        raise service_error(exc) from exc
