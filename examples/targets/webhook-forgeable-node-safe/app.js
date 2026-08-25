// Fully-safe control: the webhook handler VERIFIES the X-Razorpay-Signature (rejects a
// forged event → WI-1 NOT_REPRODUCED) AND deduplicates on X-Razorpay-Event-Id (a replayed
// event is a no-op → DP-2 NOT_REPRODUCED). No defect of any class.

const express = require('express')
const crypto = require('crypto')

const PORT = parseInt(process.env.PORT || '3301', 10)
const WEBHOOK_SECRET = process.env.RAZORPAY_WEBHOOK_SECRET || 'dummy_webhook_secret'
const BASE_URL = process.env.RAZORPAY_BASE_URL || 'http://localhost:8001'

const fulfillment = Object.create(null)
const processedEvents = new Set() // dedup key: X-Razorpay-Event-Id
const app = express()

app.get('/health', (_req, res) => res.json({ status: 'ok' }))

app.post('/webhook', express.raw({ type: '*/*' }), (req, res) => {
  const raw = req.body
  const sig = req.get('X-Razorpay-Signature') || ''
  const eventId = req.get('X-Razorpay-Event-Id') || ''
  const expected = crypto.createHmac('sha256', WEBHOOK_SECRET).update(raw).digest('hex')
  // Constant-time compare; reject anything that doesn't match.
  const ok = sig.length === expected.length &&
    crypto.timingSafeEqual(Buffer.from(sig), Buffer.from(expected))
  if (!ok) return res.status(400).json({ error: 'invalid signature' })

  let event
  try {
    event = JSON.parse(raw.toString('utf8'))
  } catch {
    return res.status(400).json({ error: 'bad json' })
  }
  const orderId = event?.payload?.payment?.entity?.order_id || 'unknown'
  // Idempotency guard: ignore a replayed event.
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

app.listen(PORT, () => console.log(`webhook-forgeable-safe target on ${PORT} (gateway=${BASE_URL})`))
