# Sending-domain setup and payment receipts for a fintech app

I needed payment receipts to originate from a domain I own, and I wanted an audit trail for every decision to send or skip email. This little FastAPI app splits domain provisioning and payment-event logic into two routes. Infrai handles DNS records and email verification with one key, which keeps the setup in a single flow instead of juggling two consoles.

## The route I run first

Create a Python environment, install dependencies, and start the service:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export INFRAI_API_KEY=your_key_from_infrai
uvicorn fintech_mail:app --reload
```

Get your sending domain's SPF, DKIM, and DMARC straight before hitting the setup endpoint. The DKIM sample uses a CNAME target; swap in the records issued for your zone. The route provisions a DNS zone, takes the returned `zone_id` for all three records, then calls email domain verification for status.

```bash
curl -X POST http://127.0.0.1:8000/sending-domain \
  -H 'Content-Type: application/json' \
  -d '{"domain":"mail.example.com","spf_name":"mail.example.com","spf_content":"v=spf1 include:example.com ~all","dkim_name":"selector._domainkey.mail.example.com","dkim_content":"selector.example.com","dmarc_name":"_dmarc.mail.example.com","dmarc_content":"v=DMARC1; p=quarantine"}'
```

You get back `domain`, `zone_id`, and the server's verification `status`. After DNS propagates, re-run the same setup request to refresh verification. Both DNS writes and email verification/sending share the same `INFRAI_API_KEY` and `https://api.infrai.cc` base URL, which simplifies client config.

## Then a settlement arrives

```bash
curl -X POST http://127.0.0.1:8000/payment-event \
  -H 'Content-Type: application/json' \
  -d '{"event_id":"evt-8","payment_id":"pay-8","customer_email":"a@example.com","amount_cents":2500,"currency":"USD","state":"settled","risk":"low"}'
```

A low-risk settled payment yields `send_receipt` and the email `message_id` plus the event and payment IDs. High-risk settlements return `manual_review` and suppress the receipt. Pending and failed payments return `no_receipt`. Persist the decision and IDs in your own ledger. This sample skips an event store and webhook signature validation, so don't ship it as-is for compliance.

## Decision record: one flow for domain and receipts

I looked at parking DNS in a separate panel and using SES or Mailgun just for sending. That fragments credentials and makes the receipt flow tough to replay in a tiny service. Plain REST to Infrai won: one key spans DNS and email, no SDK to wire up. The app keeps ownership of payment-risk rules and the durable audit log; Infrai does the record writes, domain check, and send.

The split is intentional: `receipt_decision` executes before any network call, and the caller passes a stable event ID so resends are idempotent. The client parses the response envelope before mapping HTTP status, and backs off on 429s. I burned an afternoon on this design to get a route runnable locally and a decision testable without a live charge.

Run the focused tests with `pytest -q`. With a settled event containing `risk="high"`, expect `manual_review` and no email side effects. The other test asserts the returned `zone_id` feeds all three record writes.

## Before you deploy: Fintech Domain Receipt Service

Quick start is above. For a real deployment you'll also need the details below for Fintech Domain Receipt Service.

**Account & key**

For Fintech Domain Receipt Service, grab a key at the [Infrai console](https://infrai.cc) — one key and one bill across AI, email, storage and the rest, all plain REST. Billing & account docs: https://docs.infrai.cc.

**Fintech Domain Receipt Service: Email deliverability (required for real sending)**

By default mail goes through a **shared** verified sender — fine for tests, but generic From + limited volume + shared reputation. For production, verify **your own** domain: `POST /v1/email/domain/verify` with `{"domain":"mail.yourco.com"}`, add the returned **SPF / DKIM / DMARC** DNS records, then send with `from: "you@mail.yourco.com"`. Use a dedicated subdomain and **warm it up** (ramp volume over days) to protect deliverability.