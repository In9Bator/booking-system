from flask import Flask, request, jsonify, render_template, redirect, url_for
import os, json
from datetime import datetime as _dt, timedelta as _td
import psycopg2
from psycopg2.extras import RealDictCursor
from pywebpush import webpush, WebPushException

app = Flask(__name__)

# ---- 設定 ----
def _generate_slots():
    slots, t, end = [], _dt.strptime("9:30", "%H:%M"), _dt.strptime("16:00", "%H:%M")
    while t <= end:
        slots.append(t.strftime("%H:%M"))
        t += _td(minutes=15)
    return slots

SLOTS = _generate_slots()
MAX_CAP = 2

# ---- VAPID設定 ----
VAPID_PRIVATE_KEY = os.environ.get("VAPID_PRIVATE_KEY", "")
VAPID_PUBLIC_KEY  = os.environ.get("VAPID_PUBLIC_KEY", "")
VAPID_CLAIMS      = {"sub": "mailto:" + os.environ.get("VAPID_EMAIL", "admin@example.com")}

# ---- DB接続 ----
DATABASE_URL = os.environ.get("DATABASE_URL")

def get_db():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS reservations (
            id        SERIAL PRIMARY KEY,
            timeslot  TEXT NOT NULL,
            name      TEXT NOT NULL DEFAULT '',
            called    BOOLEAN NOT NULL DEFAULT FALSE,
            ready     BOOLEAN NOT NULL DEFAULT FALSE,
            completed BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)
    # 既存テーブルへのname列追加（マイグレーション）
    cur.execute("ALTER TABLE reservations ADD COLUMN IF NOT EXISTS name TEXT NOT NULL DEFAULT ''")
    # passwordカラムが残っている場合は削除
    cur.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='reservations' AND column_name='password'
            ) THEN
                ALTER TABLE reservations DROP COLUMN password;
            END IF;
        END$$;
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS push_subscriptions (
            id             SERIAL PRIMARY KEY,
            reservation_id INTEGER NOT NULL,
            subscription   TEXT NOT NULL
        )
    """)
    conn.commit()
    cur.close()
    conn.close()

with app.app_context():
    init_db()

# ---- ヘルパー ----
def get_all_reservations():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM reservations ORDER BY id")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    result = {slot: [] for slot in SLOTS}
    for row in rows:
        slot = row["timeslot"]
        if slot in result:
            result[slot].append({
                "id":        row["id"],
                "timeslot":  row["timeslot"],
                "name":      row["name"],
                "called":    row["called"],
                "ready":     row["ready"],
                "completed": row["completed"],
            })
    return result

def get_slot_count(timeslot):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) as cnt FROM reservations WHERE timeslot = %s", (timeslot,))
    cnt = cur.fetchone()["cnt"]
    cur.close()
    conn.close()
    return cnt

def send_push_notification(reservation_id, title, body):
    if not VAPID_PRIVATE_KEY or not VAPID_PUBLIC_KEY:
        return
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT subscription FROM push_subscriptions WHERE reservation_id = %s", (reservation_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    for row in rows:
        try:
            sub = json.loads(row["subscription"])
            webpush(
                subscription_info=sub,
                data=json.dumps({"title": title, "body": body}),
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims=VAPID_CLAIMS,
            )
        except WebPushException:
            pass

# ---- ルーティング ----

@app.route("/")
def index():
    counts = {slot: get_slot_count(slot) for slot in SLOTS}
    return render_template("client.html", slots=SLOTS, counts=counts, maxcap=MAX_CAP)

@app.route("/confirm", methods=["POST"])
def confirm():
    timeslot = request.form.get("timeslot")
    name     = request.form.get("name", "").strip()
    if not timeslot or not name:
        return redirect(url_for("index"))
    return render_template("confirm.html", timeslot=timeslot, name=name)

@app.route("/reserve", methods=["POST"])
def reserve():
    timeslot = request.form.get("timeslot")
    if not timeslot or timeslot not in SLOTS:
        return redirect(url_for("index"))
    if get_slot_count(timeslot) >= MAX_CAP:
        return redirect(url_for("index"))
    name = request.form.get("name", "").strip()
    conn = get_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO reservations (timeslot, name) VALUES (%s, %s) RETURNING id", (timeslot, name))
    new_id = cur.fetchone()["id"]
    conn.commit()
    cur.close()
    conn.close()
    return render_template("result.html", number=new_id, timeslot=timeslot, name=name)

@app.route("/admin")
def admin():
    return render_template("admin.html")

@app.route("/store")
def store():
    return render_template("store.html")

@app.route("/status")
def status():
    return render_template("client_status.html")

@app.route("/admin_data")
def admin_data():
    return jsonify(get_all_reservations())

@app.route("/update", methods=["POST"])
def update():
    try:
        id_ = int(request.form.get("id"))
    except (TypeError, ValueError):
        return jsonify({"status": "invalid id"}), 400
    field = request.form.get("field")
    value = request.form.get("value")
    if field not in ("called", "ready", "completed"):
        return jsonify({"status": "invalid field"}), 400
    bool_value = (value == "1")
    conn = get_db()
    cur = conn.cursor()
    if field == "completed" and not bool_value:
        cur.execute(
            "UPDATE reservations SET completed = %s, called = FALSE, ready = FALSE WHERE id = %s",
            (bool_value, id_)
        )
    else:
        cur.execute(f"UPDATE reservations SET {field} = %s WHERE id = %s", (bool_value, id_))
    conn.commit()
    cur.close()
    conn.close()
    if field == "called" and bool_value:
        send_push_notification(id_, "🔔 呼び出されています", "受付カウンターへお越しください")
    return jsonify({"status": "ok"})

@app.route("/subscribe", methods=["POST"])
def subscribe():
    data = request.get_json()
    reservation_id = data.get("reservation_id")
    subscription   = json.dumps(data.get("subscription"))
    if not reservation_id or not subscription:
        return jsonify({"status": "error"}), 400
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM push_subscriptions WHERE reservation_id = %s", (reservation_id,))
    cur.execute(
        "INSERT INTO push_subscriptions (reservation_id, subscription) VALUES (%s, %s)",
        (reservation_id, subscription)
    )
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"status": "ok"})

@app.route("/staff")
def staff():
    counts = {slot: get_slot_count(slot) for slot in SLOTS}
    return render_template("staff.html", slots=SLOTS, counts=counts, maxcap=MAX_CAP)

@app.route("/staff_reserve", methods=["POST"])
def staff_reserve():
    data     = request.get_json()
    name     = (data.get("name") or "").strip()
    timeslot = data.get("timeslot")
    if not name or not timeslot or timeslot not in SLOTS:
        return jsonify({"status": "error", "message": "入力が不正です"}), 400
    if get_slot_count(timeslot) >= MAX_CAP:
        return jsonify({"status": "error", "message": "その時間帯は満員です"}), 400
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("INSERT INTO reservations (timeslot, name) VALUES (%s, %s) RETURNING id", (timeslot, name))
    new_id = cur.fetchone()["id"]
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"status": "ok", "number": new_id, "timeslot": timeslot})

@app.route("/reset_db", methods=["POST"])
def reset_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("TRUNCATE TABLE reservations, push_subscriptions RESTART IDENTITY")
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    app.run(debug=True, port=5000)
