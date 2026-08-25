// Vulnerable merchant: the webhook handler FULFILLS without verifying the
// X-Razorpay-Signature. A forged event (any/invalid signature) is accepted, so an
// attacker can release goods for free — the WEBHOOK_INTEGRITY (WI-1) defect.

const express = require('express')

const PORT = parseInt(process.env.PORT || '3300', 10)
const BASE_URL = process.env.RAZORPAY_BASE_URL || 'http://localhost:8001'

const fulfillment = Object.create(null)
const app = express()

app.get('/health', (_req, res) => res.json({ status: 'ok' }))

app.post('/webhook', express.raw({ type: '*/*' }), (req, res) => {
  // BUG: no signature verification at all — trusts any POST.
  let event
  try {
    event = JSON.parse(req.body.toString('utf8'))
  } catch {
    return res.status(400).json({ error: 'bad json' })
  }
  const orderId = event?.payload?.payment?.entity?.order_id || 'unknown'
  fulfillment[orderId] = (fulfillment[orderId] || 0) + 1
  return res.json({ status: 'fulfilled', order_id: orderId, fulfilled_count: fulfillment[orderId] })
})

app.get('/state', (req, res) => {
  const orderId = String(req.query.order_id || '')
  res.json({ order_id: orderId, fulfilled_count: fulfillment[orderId] || 0 })
})

app.listen(PORT, () => console.log(`webhook-forgeable target on ${PORT} (gateway=${BASE_URL})`))
