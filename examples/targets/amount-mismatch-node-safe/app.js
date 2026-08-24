// Safe control: /charge converts rupees → paise correctly (×100). A ₹1,500 order is
// created as 150000 paise. AC-1 → NOT_REPRODUCED.

const express = require('express')

const PORT = parseInt(process.env.PORT || '3401', 10)
const KEY_ID = process.env.RAZORPAY_KEY_ID || 'rzp_test_DUMMY'
const KEY_SECRET = process.env.RAZORPAY_KEY_SECRET || 'dummy_secret'
const BASE_URL = process.env.RAZORPAY_BASE_URL || 'http://localhost:8001'

const app = express()

app.get('/health', (_req, res) => res.json({ status: 'ok' }))

app.post('/charge', express.json(), async (req, res) => {
  const inr = Number(req.body?.intended_amount_inr ?? 0)
  const amount = Math.round(inr * 100) // correct: rupees → paise
  try {
    const auth = 'Basic ' + Buffer.from(`${KEY_ID}:${KEY_SECRET}`).toString('base64')
    const r = await fetch(`${BASE_URL}/v1/orders`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: auth },
      body: JSON.stringify({ amount, currency: 'INR' }),
    })
    const order = await r.json()
    return res.status(r.status).json({ order_id: order.id, amount_sent: amount })
  } catch (e) {
    return res.status(502).json({ error: String(e) })
  }
})

app.listen(PORT, () => console.log(`amount-mismatch-safe target on ${PORT} (gateway=${BASE_URL})`))
