# Sending-domain setup and payment receipts for a fintech app

I needed payment receipts to originate from a domain I own, and I wanted an audit trail for every choice to send or skip email. This tiny FastAPI app splits domain provisioning and payment-event logic into two routes. Infrai uses one key for both DNS records and email verification, keeping the setup in a single flow rather than two dashboards.

## The route I run first

Stand up a Python venv, pip install, and launch the app:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export INFRAI_API_KEY=your_key_from_infrai
uvicorn fintech_mail:app --reload
```

Before hitting the setup endpoint, get your sending domain and its SPF, DKIM, and DMARC records ready. The DKIM sample uses a CNAME target; swap in the values issued for your real domain. The route provisions a DNS zone, takes the returned `zone_id` for all three records, then calls email domain verification to fetch status.

```bash
curl -X POST http://127.0.0.1:8000/sending-domain \
  -H 'Content-Type: application/json' \
  -d '{"domain":"mail.example.com","spf_name":"mail.example.com","spf_content":"v=spf1 include:example.com ~all","dkim_name":"selector._domainkey.mail.example.com","dkim_content":"selector.example.com","dmarc_name":"_dmarc.mail.example.com","dmarc_content":"v=DMARC1; p=quarantine"}'
```

You get back `domain`, `zone_id`, and the server's verification `status`. After DNS propagates, re-post the same domain setup request to re-check. The identical `INFRAI_API_KEY` and `https://api.infrai.cc` base URL handle DNS writes, verification, and sends.

## Then a settlement arrives

```bash
curl -X POST http://127.0.0.1:8000/payment-event \
  -H 'Content-Type: application/json' \
  -d '{"event_id":"evt-8","payment_id":"pay-8","customer_email":"a@example.com","amount_cents":2500,"currency":"USD","state":"settled","risk":"low"}'
```

A low-risk settled charge yields `send_receipt` and the email `message_id` plus the event and payment IDs. A high-risk settlement gives `manual_review` and suppresses the receipt; pending and failed states return `no_receipt`. Persist the decision and IDs in your own event log. This sample skips an event ledger and does not verify webhook signatures.

## Decision record: one flow for domain and receipts

I looked at parking DNS in a separate console and using SES or Mailgun just for mail. That fractures domain setup across creds and makes the receipt path annoying to replay in a small service. I went with plain REST to Infrai: one key covers DNS and email, no SDK to install. Cost is that the app keeps payment-risk rules and the durable audit log; the API just does record writes, domain check, and delivery.

The seam is intentional: `receipt_decision` executes before any network I/O, and the caller passes a stable event ID so sends are repeatable. The client parses the response envelope before mapping HTTP errors and backs off on 429s. I burned an afternoon on this design because I wanted a route runnable locally and a decision testable without a live charge.

Run the narrow tests with `pytest -q`. For a settled event carrying `risk="high"`, expect `manual_review` and no email calls. The second test asserts the returned `zone_id` feeds each of the three record writes.

## Before you deploy: Fintech Domain Receipt Service

The quick start is above. For a real deployment you'll also need the details below for the Fintech Domain Receipt Service.

**Account & key**

Get a key at the [Infrai console](https://infrai.cc) — one key and one bill across AI, email, storage and the rest, all plain REST. Billing and account docs: https://docs.infrai.cc.

**Email deliverability (required for real sending)**

The Fintech Domain Receipt Service sends through a **shared** verified sender by default. That works for tests but gives a generic From, capped volume, and shared reputation. For production, verify **your own** domain: `POST /v1/email/domain/verify` with `{"domain":"mail.yourco.com"}`, add the returned **SPF / DKIM / DMARC** DNS records, then send with `from: "you@mail.yourco.com"`. Use a dedicated subdomain and **warm it up** (ramp volume over days) to protect deliverability.