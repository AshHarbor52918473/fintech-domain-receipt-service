from fintech_mail import PaymentEvent, SendingDomain, notify, onboard


def test_high_risk_settlement_never_emits_receipt(monkeypatch):
    def unexpected(*args):
        raise AssertionError("High-risk events must not send email")

    monkeypatch.setattr("fintech_mail.call", unexpected)
    event = PaymentEvent(event_id="evt-8", payment_id="pay-8", customer_email="a@example.com",
                         amount_cents=2500, currency="USD", state="settled", risk="high")
    assert notify(event) == {"event_id": "evt-8", "payment_id": "pay-8", "decision": "manual_review"}


def test_zone_id_is_used_for_each_record(monkeypatch):
    requests = []

    def fake_call(method, path, payload, operation_id):
        requests.append((path, payload))
        if path == "/v1/dns/domain/add":
            return {"zone_id": "zone-42"}
        if path == "/v1/email/domain/verify":
            return {"verification": {"status": "verified"}}
        return {}

    monkeypatch.setattr("fintech_mail.call", fake_call)
    domain = SendingDomain(domain="mail.example.com", spf_name="mail.example.com",
                           spf_content="v=spf1 include:example.com ~all",
                           dkim_name="selector._domainkey.mail.example.com",
                           dkim_content="selector.example.com", dmarc_name="_dmarc.mail.example.com",
                           dmarc_content="v=DMARC1; p=quarantine")
    assert onboard(domain)["status"] == "verified"
    assert len([payload for path, payload in requests if path == "/v1/dns/record/upsert"
                and payload["zone_id"] == "zone-42"]) == 3
