"""
Dataset generator: creates seeded-variant samples from templates.

Templates are Flask/FastAPI/Express mini-shops with charge + webhook + refund endpoints.
Variants inject specific defects at known line ranges.
All generated samples are written to dataset/raw/<sample_id>/.
"""
from __future__ import annotations

import json
import textwrap
import uuid
from pathlib import Path

DATASET_RAW = Path(__file__).parent.parent.parent / "dataset" / "raw"


# ─── Flask template ────────────────────────────────────────────────────────────

def _flask_safe(repo_id: str) -> dict:
    """Fully safe Flask mini-shop."""
    code = textwrap.dedent("""\
        import hashlib
        import hmac
        import os
        from decimal import Decimal

        import razorpay
        from flask import Flask, abort, jsonify, request

        app = Flask(__name__)
        KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "rzp_test_DUMMY")
        KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "dummy")
        WEBHOOK_SECRET = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "dummy")
        BASE_URL = os.environ.get("RAZORPAY_BASE_URL", "")

        opts = {"auth": (KEY_ID, KEY_SECRET)}
        if BASE_URL:
            opts["base_url"] = BASE_URL
        client = razorpay.Client(**opts)

        # In-memory store (production: use a database)
        _processed_events: set = set()
        _orders: dict = {}


        @app.route("/health")
        def health():
            return jsonify({"status": "ok"})


        @app.route("/create-order", methods=["POST"])
        def create_order():
            data = request.json or {}
            cart_id = data.get("cart_id", "cart_001")

            # Safe: check for existing order first
            if cart_id in _orders:
                return jsonify({"order_id": _orders[cart_id]["id"]})

            # Safe: amount computed server-side, already in paise
            amount_paise = 150000  # ₹1500 in paise

            order = client.order.create({
                "amount": amount_paise,
                "currency": "INR",
                "receipt": cart_id,
            })
            _orders[cart_id] = order
            return jsonify({"order_id": order["id"], "amount": order["amount"]})


        @app.route("/webhook/razorpay", methods=["POST"])
        def webhook():
            raw_body = request.get_data(as_text=False)
            sig = request.headers.get("X-Razorpay-Signature", "")
            event_id = request.headers.get("X-Razorpay-Event-Id", "")

            # Safe: verify over raw bytes
            try:
                client.utility.verify_webhook_signature(
                    raw_body.decode(), sig, WEBHOOK_SECRET
                )
            except Exception:
                abort(400, "Invalid signature")

            # Safe: event-id dedup
            if event_id in _processed_events:
                return jsonify({"status": "already_processed"}), 200
            _processed_events.add(event_id)

            payload = request.json
            if payload.get("event") == "payment.captured":
                payment = payload["payload"]["payment"]["entity"]
                _fulfill(payment["id"], payment["amount"])

            return jsonify({"status": "ok"}), 200


        def _fulfill(payment_id: str, amount: int) -> None:
            app.logger.info(f"Fulfilling {payment_id}")


        if __name__ == "__main__":
            app.run(host="0.0.0.0", port=5050)
    """)
    return {"code": code, "labels": [], "hard_negative": False, "difficulty": 1}


def _flask_dp2_vuln(repo_id: str) -> dict:
    """DP-2 vulnerable: webhook fulfills without event-id dedup."""
    code = textwrap.dedent("""\
        import os
        import razorpay
        from flask import Flask, jsonify, request

        app = Flask(__name__)
        KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "rzp_test_DUMMY")
        KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "dummy")
        WEBHOOK_SECRET = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "dummy")
        BASE_URL = os.environ.get("RAZORPAY_BASE_URL", "")

        opts = {"auth": (KEY_ID, KEY_SECRET)}
        if BASE_URL:
            opts["base_url"] = BASE_URL
        client = razorpay.Client(**opts)

        _orders: dict = {}


        @app.route("/health")
        def health():
            return jsonify({"status": "ok"})


        @app.route("/create-order", methods=["POST"])
        def create_order():
            data = request.json or {}
            amount_paise = 150000
            order = client.order.create({"amount": amount_paise, "currency": "INR"})
            _orders[order["id"]] = order
            return jsonify({"order_id": order["id"]})


        @app.route("/webhook/razorpay", methods=["POST"])
        def webhook():
            raw_body = request.get_data(as_text=False)
            sig = request.headers.get("X-Razorpay-Signature", "")
            try:
                client.utility.verify_webhook_signature(
                    raw_body.decode(), sig, WEBHOOK_SECRET
                )
            except Exception:
                return jsonify({"error": "bad sig"}), 400

            # DEFECT DP-2: no event-id dedup — Razorpay retries for 24h
            payload = request.json
            if payload.get("event") == "payment.captured":
                payment = payload["payload"]["payment"]["entity"]
                _fulfill(payment["id"], payment["amount"])

            return jsonify({"status": "ok"}), 200


        def _fulfill(payment_id: str, amount: int) -> None:
            app.logger.info(f"Fulfilling {payment_id}")


        if __name__ == "__main__":
            app.run(host="0.0.0.0", port=5050)
    """)
    return {
        "code": code,
        "labels": [{"defect_class": "DUPLICATE_PAYMENT", "lines": [[32, 42]], "scenario_ids": ["DP-2"]}],
        "hard_negative": False,
        "difficulty": 2,
    }


def _flask_wi1_vuln(repo_id: str) -> dict:
    """WI-1 vulnerable: no signature verification."""
    code = textwrap.dedent("""\
        import os
        import razorpay
        from flask import Flask, jsonify, request

        app = Flask(__name__)
        KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "rzp_test_DUMMY")
        KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "dummy")
        BASE_URL = os.environ.get("RAZORPAY_BASE_URL", "")

        opts = {"auth": (KEY_ID, KEY_SECRET)}
        if BASE_URL:
            opts["base_url"] = BASE_URL
        client = razorpay.Client(**opts)
        _fulfilled: list = []


        @app.route("/health")
        def health():
            return jsonify({"status": "ok"})


        @app.route("/create-order", methods=["POST"])
        def create_order():
            amount_paise = 150000
            order = client.order.create({"amount": amount_paise, "currency": "INR"})
            return jsonify({"order_id": order["id"]})


        @app.route("/webhook/razorpay", methods=["POST"])
        def webhook():
            # DEFECT WI-1: no signature check at all
            payload = request.json
            if payload.get("event") == "payment.captured":
                payment = payload["payload"]["payment"]["entity"]
                _fulfilled.append(payment["id"])
                _fulfill(payment["id"], payment["amount"])
            return jsonify({"status": "ok"}), 200


        def _fulfill(payment_id: str, amount: int) -> None:
            app.logger.info(f"Fulfilling {payment_id}")


        if __name__ == "__main__":
            app.run(host="0.0.0.0", port=5050)
    """)
    return {
        "code": code,
        "labels": [
            {"defect_class": "WEBHOOK_INTEGRITY", "lines": [[30, 37]], "scenario_ids": ["WI-1"]},
            {"defect_class": "DUPLICATE_PAYMENT", "lines": [[30, 37]], "scenario_ids": ["DP-2"]},
        ],
        "hard_negative": False,
        "difficulty": 1,
    }


def _flask_ac1_vuln(repo_id: str) -> dict:
    """AC-1 vulnerable: rupees instead of paise. Safe webhook + dedup so AC is the only defect."""
    code = textwrap.dedent("""\
        import os
        import razorpay
        from flask import Flask, abort, jsonify, request

        app = Flask(__name__)
        KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "rzp_test_DUMMY")
        KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "dummy")
        WEBHOOK_SECRET = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "dummy")
        BASE_URL = os.environ.get("RAZORPAY_BASE_URL", "")

        opts = {"auth": (KEY_ID, KEY_SECRET)}
        if BASE_URL:
            opts["base_url"] = BASE_URL
        client = razorpay.Client(**opts)

        _orders: dict = {}
        _processed_events: set = set()


        @app.route("/health")
        def health():
            return jsonify({"status": "ok"})


        @app.route("/create-order", methods=["POST"])
        def create_order():
            data = request.json or {}
            cart_id = data.get("cart_id", "cart_001")
            if cart_id in _orders:
                return jsonify({"order_id": _orders[cart_id]["id"]})
            amount_inr = data.get("intended_amount_inr", 1500)
            # DEFECT AC-1: passes rupees where Razorpay expects paise
            order = client.order.create({
                "amount": amount_inr,
                "currency": "INR",
            })
            _orders[cart_id] = order
            return jsonify({"order_id": order["id"], "amount": order["amount"]})


        @app.route("/webhook/razorpay", methods=["POST"])
        def webhook():
            raw_body = request.get_data(as_text=False)
            sig = request.headers.get("X-Razorpay-Signature", "")
            event_id = request.headers.get("X-Razorpay-Event-Id", "")
            try:
                client.utility.verify_webhook_signature(raw_body.decode(), sig, WEBHOOK_SECRET)
            except Exception:
                abort(400, "Invalid signature")
            if event_id in _processed_events:
                return jsonify({"status": "already_processed"}), 200
            _processed_events.add(event_id)
            payload = request.json
            if payload.get("event") == "payment.captured":
                payment = payload["payload"]["payment"]["entity"]
                _fulfill(payment["id"], payment["amount"])
            return jsonify({"status": "ok"}), 200


        def _fulfill(payment_id: str, amount: int) -> None:
            app.logger.info(f"Fulfilling {payment_id}")


        if __name__ == "__main__":
            app.run(host="0.0.0.0", port=5050)
    """)
    return {
        "code": code,
        "labels": [{"defect_class": "AMOUNT_CURRENCY", "lines": [[30, 38]], "scenario_ids": ["AC-1"]}],
        "hard_negative": False,
        "difficulty": 1,
    }


def _flask_ac3_vuln(repo_id: str) -> dict:
    """AC-3 vulnerable: client-supplied amount. Safe webhook + dedup so AC is the only defect."""
    code = textwrap.dedent("""\
        import os
        import razorpay
        from flask import Flask, abort, jsonify, request

        app = Flask(__name__)
        KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "rzp_test_DUMMY")
        KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "dummy")
        WEBHOOK_SECRET = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "dummy")
        BASE_URL = os.environ.get("RAZORPAY_BASE_URL", "")

        opts = {"auth": (KEY_ID, KEY_SECRET)}
        if BASE_URL:
            opts["base_url"] = BASE_URL
        client = razorpay.Client(**opts)

        _orders: dict = {}
        _processed_events: set = set()


        @app.route("/health")
        def health():
            return jsonify({"status": "ok"})


        @app.route("/create-order", methods=["POST"])
        def create_order():
            data = request.json or {}
            cart_id = data.get("cart_id", "cart_001")
            if cart_id in _orders:
                return jsonify({"order_id": _orders[cart_id]["id"]})
            # DEFECT AC-3: amount from client request body — tamper to pay ₹0.01
            amount = request.json["amount"]
            order = client.order.create({
                "amount": amount,
                "currency": "INR",
            })
            _orders[cart_id] = order
            return jsonify({"order_id": order["id"], "amount": order["amount"]})


        @app.route("/webhook/razorpay", methods=["POST"])
        def webhook():
            raw_body = request.get_data(as_text=False)
            sig = request.headers.get("X-Razorpay-Signature", "")
            event_id = request.headers.get("X-Razorpay-Event-Id", "")
            try:
                client.utility.verify_webhook_signature(raw_body.decode(), sig, WEBHOOK_SECRET)
            except Exception:
                abort(400, "Invalid signature")
            if event_id in _processed_events:
                return jsonify({"status": "already_processed"}), 200
            _processed_events.add(event_id)
            payload = request.json
            if payload.get("event") == "payment.captured":
                payment = payload["payload"]["payment"]["entity"]
                _fulfill(payment["id"], payment["amount"])
            return jsonify({"status": "ok"}), 200


        def _fulfill(payment_id: str, amount: int) -> None:
            app.logger.info(f"Fulfilling {payment_id}")


        if __name__ == "__main__":
            app.run(host="0.0.0.0", port=5050)
    """)
    return {
        "code": code,
        "labels": [{"defect_class": "AMOUNT_CURRENCY", "lines": [[31, 38]], "scenario_ids": ["AC-3"]}],
        "hard_negative": False,
        "difficulty": 2,
    }


def _flask_hard_negative_decimal(repo_id: str) -> dict:
    """Hard negative: Decimal arithmetic for GST. Fully safe — no DP/WI/AC defects."""
    code = textwrap.dedent("""\
        import os
        from decimal import Decimal, ROUND_HALF_UP
        import razorpay
        from flask import Flask, abort, jsonify, request

        app = Flask(__name__)
        KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "rzp_test_DUMMY")
        KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "dummy")
        WEBHOOK_SECRET = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "dummy")
        BASE_URL = os.environ.get("RAZORPAY_BASE_URL", "")

        opts = {"auth": (KEY_ID, KEY_SECRET)}
        if BASE_URL:
            opts["base_url"] = BASE_URL
        client = razorpay.Client(**opts)

        _orders: dict = {}
        _processed_events: set = set()


        @app.route("/health")
        def health():
            return jsonify({"status": "ok"})


        @app.route("/create-order", methods=["POST"])
        def create_order():
            data = request.json or {}
            cart_id = data.get("cart_id", "default")
            if cart_id in _orders:
                return jsonify({"order_id": _orders[cart_id]["id"]})
            # Safe: Decimal arithmetic for GST, rounded to integer paise
            base_price = Decimal("1500.00")
            gst_rate = Decimal("0.18")
            total_inr = (base_price * (1 + gst_rate)).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            amount_paise = int(total_inr * 100)
            order = client.order.create({
                "amount": amount_paise,
                "currency": "INR",
            })
            _orders[cart_id] = order
            return jsonify({"order_id": order["id"]})


        @app.route("/webhook/razorpay", methods=["POST"])
        def webhook():
            raw_body = request.get_data(as_text=False)
            sig = request.headers.get("X-Razorpay-Signature", "")
            event_id = request.headers.get("X-Razorpay-Event-Id", "")
            try:
                client.utility.verify_webhook_signature(raw_body.decode(), sig, WEBHOOK_SECRET)
            except Exception:
                abort(400, "Invalid signature")
            if event_id in _processed_events:
                return jsonify({"status": "already_processed"}), 200
            _processed_events.add(event_id)
            payload = request.json
            if payload.get("event") == "payment.captured":
                payment = payload["payload"]["payment"]["entity"]
                _fulfill(payment["id"], payment["amount"])
            return jsonify({"status": "ok"}), 200


        def _fulfill(payment_id: str, amount: int) -> None:
            app.logger.info(f"Fulfilling {payment_id}")


        if __name__ == "__main__":
            app.run(host="0.0.0.0", port=5050)
    """)
    return {
        "code": code,
        "labels": [],
        "hard_negative": True,
        "difficulty": 4,
    }


def _flask_hard_negative_paise_named(repo_id: str) -> dict:
    """Hard negative: variable already named amount_paise. Fully safe — no DP/WI/AC defects."""
    code = textwrap.dedent("""\
        import os
        import razorpay
        from flask import Flask, abort, jsonify, request

        app = Flask(__name__)
        KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "rzp_test_DUMMY")
        KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "dummy")
        WEBHOOK_SECRET = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "dummy")
        BASE_URL = os.environ.get("RAZORPAY_BASE_URL", "")

        opts = {"auth": (KEY_ID, KEY_SECRET)}
        if BASE_URL:
            opts["base_url"] = BASE_URL
        client = razorpay.Client(**opts)

        PRODUCT_PRICE_PAISE = 150000  # ₹1500 in paise
        _orders: dict = {}
        _processed_events: set = set()


        @app.route("/health")
        def health():
            return jsonify({"status": "ok"})


        @app.route("/create-order", methods=["POST"])
        def create_order():
            data = request.json or {}
            cart_id = data.get("cart_id", "default")
            if cart_id in _orders:
                return jsonify({"order_id": _orders[cart_id]["id"]})
            # Safe: amount is already in paise by convention
            amount_paise = PRODUCT_PRICE_PAISE
            order = client.order.create({
                "amount": amount_paise,
                "currency": "INR",
                "receipt": cart_id,
            })
            _orders[cart_id] = order
            return jsonify({"order_id": order["id"]})


        @app.route("/webhook/razorpay", methods=["POST"])
        def webhook():
            raw_body = request.get_data(as_text=False)
            sig = request.headers.get("X-Razorpay-Signature", "")
            event_id = request.headers.get("X-Razorpay-Event-Id", "")
            try:
                client.utility.verify_webhook_signature(raw_body.decode(), sig, WEBHOOK_SECRET)
            except Exception:
                abort(400, "Invalid signature")
            if event_id in _processed_events:
                return jsonify({"status": "already_processed"}), 200
            _processed_events.add(event_id)
            payload = request.json
            if payload.get("event") == "payment.captured":
                payment = payload["payload"]["payment"]["entity"]
                _fulfill(payment["id"], payment["amount"])
            return jsonify({"status": "ok"}), 200


        def _fulfill(payment_id: str, amount: int) -> None:
            app.logger.info(f"Fulfilling {payment_id}")


        if __name__ == "__main__":
            app.run(host="0.0.0.0", port=5050)
    """)
    return {
        "code": code,
        "labels": [],
        "hard_negative": True,
        "difficulty": 3,
    }


# ─── Template registry ────────────────────────────────────────────────────────

TEMPLATES = {
    "flask_safe": _flask_safe,
    "flask_dp2_vuln": _flask_dp2_vuln,
    "flask_wi1_vuln": _flask_wi1_vuln,
    "flask_ac1_vuln": _flask_ac1_vuln,
    "flask_ac3_vuln": _flask_ac3_vuln,
    "flask_hn_decimal": _flask_hard_negative_decimal,
    "flask_hn_paise_named": _flask_hard_negative_paise_named,
}


def generate_samples(count_per_template: int = 3, output_dir: Path | None = None) -> list[Path]:
    """
    Generate seeded variant samples from templates.
    Returns list of written sample directories.
    """
    out = output_dir or DATASET_RAW
    out.mkdir(parents=True, exist_ok=True)
    written = []

    for template_name, template_fn in TEMPLATES.items():
        for variant in range(count_per_template):
            sample_id = f"gen-{template_name}-v{variant}"
            repo_id = f"repo-{template_name}-v{variant}"  # unique repo_id per variant
            sample_dir = out / sample_id
            sample_dir.mkdir(exist_ok=True)

            data = template_fn(repo_id)
            code_path = sample_dir / "app.py"
            code_path.write_text(data["code"])

            manifest = {
                "sample_id": sample_id,
                "repo_id": repo_id,
                "language": "python",
                "framework": "flask",
                "source": "SEEDED_VARIANT",
                "labels": data["labels"],
                "hard_negative": data["hard_negative"],
                "difficulty": data["difficulty"],
                "runnable": False,
                "manifest_path": None,
                "notes": f"Generated from template {template_name}, variant {variant}",
                "license": "MIT",
                "seed": f"{template_name}-v{variant}",
                "file": "app.py",
            }
            (sample_dir / "sample.json").write_text(json.dumps(manifest, indent=2))
            written.append(sample_dir)

    return written
