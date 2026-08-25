// Safe merchant: identical to dup-fulfillment-node EXCEPT it deduplicates on the
// webhook event id (X-Razorpay-Event-Id). A redelivery of the same event is a
// no-op, so fulfillment happens exactly once. This is the NOT_REPRODUCED control
// that proves the verifier does not raise false positives.

const express = require('express')
const crypto = require('crypto')

const PORT = parseInt(process.env.PORT || '3201', 10)
const KEY_ID = process.env.RAZORPAY_KEY_ID || 'rzp_test_DUMMY'
const KEY_SECRET = process.env.RAZORPAY_KEY_SECRET || 'dummy_secret'
const WEBHOOK_SECRET = process.env.RAZORPAY_WEBHOOK_SECRET || 'dummy_webhook_secret'
const BASE_URL = process.env.RAZORPAY_BASE_URL || 'http://localhost:8001'

const fulfillment = Object.create(null)
const processedEvents = new Set() // dedup key: X-Razorpay-Event-Id

const app = express()

app.get('/health', (_req, res) => res.json({ status: 'ok' }))

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

app.post('/webhook', express.raw({ type: '*/*' }), (req, res) => {
  const raw = req.body
  const sig = req.get('X-Razorpay-Signature') || ''
  const eventId = req.get('X-Razorpay-Event-Id') || ''
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

  // FIX: ignore a redelivery of an event we've already fulfilled.
  if (processedEvents.has(eventId)) {
    return res.json({ status: 'duplicate_ignored', order_id: orderId, fulfilled_count: fulfillment[orderId] || 0 })
  }
  processedEvents.add(eventId)
  fulfillment[orderId] = (fulfillment[orderId] || 0) + 1

  return res.json({ status: 'fulfilled', order_id: orderId, fulfilled_count: fulfillment[orderId] })
})

app.get('/state', (req, res) => {
  const orderId = String(req.query.order_id || '')
  res.json({ order_id: orderId, fulfilled_count: fulfillment[orderId] || 0 })
})

// Bind all interfaces (see dup-fulfillment-node/app.js for why).
app.listen(PORT, () => {
  console.log(`dup-fulfillment-safe target listening on ${PORT} (gateway=${BASE_URL})`)
})
