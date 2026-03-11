from flask import Flask, request, jsonify, render_template, redirect, url_for
import os, random, string
from datetime import datetime as _dt, timedelta as _td
import psycopg2
from psycopg2.extras import RealDictCursor

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

# ---- DB接続 ----
DATABASE_URL = os.environ.get("DATABASE_URL")

def get_db():
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    return conn

def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS reservations (
            id        SERIAL PRIMARY KEY,
            timeslot  TEXT NOT NULL,
            password  TEXT NOT NULL,
            called    BOOLEAN NOT NULL DEFAULT FALSE,
            ready     BOOLEAN NOT NULL DEFAULT FALSE,
            completed BOOLEAN NOT NULL DEFAULT FALSE
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
                "password":  row["password"],
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

# ---- ルーティング ----

@app.route("/")
def index():
    counts = {slot: get_slot_count(slot) for slot in SLOTS}
    return render_template("client.html", slots=SLOTS, counts=counts, maxcap=MAX_CAP)

@app.route("/confirm", methods=["POST"])
def confirm():
    timeslot = request.form.get("timeslot")
    password = request.form.get("password")
    if not timeslot or not password:
        return redirect(url_for("index"))
    return render_template("confirm.html", timeslot=timeslot, password=password)

@app.route("/reserve", methods=["POST"])
def reserve():
    timeslot = request.form.get("timeslot")
    password = request.form.get("password")
    if not timeslot or timeslot not in SLOTS:
        return redirect(url_for("index"))
    if get_slot_count(timeslot) >= MAX_CAP:
        return redirect(url_for("index"))
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO reservations (timeslot, password) VALUES (%s, %s) RETURNING id",
        (timeslot, password)
    )
    new_id = cur.fetchone()["id"]
    conn.commit()
    cur.close()
    conn.close()
    return render_template("result.html", number=new_id, timeslot=timeslot, password=password)

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
        cur.execute(
            f"UPDATE reservations SET {field} = %s WHERE id = %s",
            (bool_value, id_)
        )
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"status": "ok"})

@app.route("/store_action", methods=["POST"])
def store_action():
    number   = request.form.get("number")
    password = request.form.get("password")
    try:
        number = int(number)
    except (TypeError, ValueError):
        return jsonify({"status": "error"})
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM reservations WHERE id = %s AND password = %s", (number, password))
    row = cur.fetchone()
    if row:
        cur.execute("UPDATE reservations SET completed = TRUE WHERE id = %s", (number,))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"status": "ok"})
    cur.close()
    conn.close()
    return jsonify({"status": "error"})

if __name__ == "__main__":
    app.run(debug=True, port=5000)
