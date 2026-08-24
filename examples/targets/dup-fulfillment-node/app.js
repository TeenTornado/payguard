// Vulnerable merchant: fulfills an order every time a validly-signed
// payment.captured webhook arrives, WITHOUT deduplicating on the event id.
// Razorpay retries webhook deliveries; a retry therefore fulfills twice — the
// DUPLICATE_PAYMENT (DP-2) defect.
//
// Real Express app. Its Razorpay calls go to RAZORPAY_BASE_URL (the PayGuard
// EMULATE gateway) — no live keys ever enter this process.

const express = require('express')
const crypto = require('crypto')

const PORT = parseInt(process.env.PORT || '3200', 10)
const KEY_ID = process.env.RAZORPAY_KEY_ID || 'rzp_test_DUMMY'
const KEY_SECRET = process.env.RAZORPAY_KEY_SECRET || 'dummy_secret'
const WEBHOOK_SECRET = process.env.RAZORPAY_WEBHOOK_SECRET || 'dummy_webhook_secret'
const BASE_URL = process.env.RAZORPAY_BASE_URL || 'http://localhost:8001'

// Per-order fulfillment counter — the observable side effect the verifier probes.
const fulfillment = Object.create(null)

const app = express()

app.get('/health', (_req, res) => res.json({ status: 'ok' }))

// Create an order through the gateway (Razorpay-faithful). Used by AC scenarios;
// DP-2 drives fulfillment directly through webhooks.
app.post('/charge', express.json(), async (req, res) => {
  const inr = Number(req.body?.intended_amount_inr ?? 0)
  const amountPaise = Math.round(inr * 100)
  try {
    const auth = 'Basic ' + Buffer.from(`${KEY_ID}:${KEY_SECRET}`).toString('base64')
    const r = await fetch(`${BASE_URL}/v1/orders`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: auth },
      body: JSON.stringify({ amount: amountPaise, currency: 'INR' }),
    })
    const order = await r.json()
    return res.status(r.status).json({ order_id: order.id, amount: order.amount, key_id: KEY_ID })
  } catch (e) {
    return res.status(502).json({ error: String(e) })
  }
})

// Webhook receiver. Verifies the signature, then FULFILLS with no idempotency
// guard — every delivery (including a retry of the same event) fulfills again.
app.post('/webhook', express.raw({ type: '*/*' }), (req, res) => {
  const raw = req.body // Buffer (raw bytes as received — required for HMAC)
  const sig = req.get('X-Razorpay-Signature') || ''
  const expected = crypto.createHmac('sha256', WEBHOOK_SECRET).update(raw).digest('hex')
  if (!crypto.timingSafeEqual(Buffer.from(sig.padEnd(expected.length)), Buffer.from(expected))) {
    return res.status(400).json({ error: 'invalid signature' })
  }

  let event
  try {
    event = JSON.parse(raw.toString('utf8'))
  } catch {
    return res.status(400).json({ error: 'bad json' })
  }
  const entity = event?.payload?.payment?.entity || {}
  const orderId = entity.order_id || 'unknown'

  // BUG: no check against X-Razorpay-Event-Id / payment id before fulfilling.
  fulfillment[orderId] = (fulfillment[orderId] || 0) + 1

  return res.json({ status: 'fulfilled', order_id: orderId, fulfilled_count: fulfillment[orderId] })
})

// State probe — the verifier reads fulfilled_count here.
app.get('/state', (req, res) => {
  const orderId = String(req.query.order_id || '')
  res.json({ order_id: orderId, fulfilled_count: fulfillment[orderId] || 0 })
})

app.listen(PORT, '127.0.0.1', () => {
  console.log(`dup-fulfillment target listening on ${PORT} (gateway=${BASE_URL})`)
})
