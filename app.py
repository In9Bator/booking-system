from flask import Flask, request, jsonify, render_template, redirect, url_for
import random, string
from datetime import datetime as _dt, timedelta as _td

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

# ---- データストア（インメモリ） ----
reservations: dict = {slot: [] for slot in SLOTS}
counter = {"n": 0}

def get_counts():
    return {slot: len(reservations[slot]) for slot in SLOTS}

# ---- ルーティング ----

@app.route("/")
def index():
    counts = get_counts()
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
    if len(reservations[timeslot]) >= MAX_CAP:
        return redirect(url_for("index"))
    counter["n"] += 1
    entry = {
        "id": counter["n"],
        "password": password,
        "called": False,
        "ready": False,
        "completed": False,
    }
    reservations[timeslot].append(entry)
    return render_template("result.html", number=entry["id"], timeslot=timeslot, password=password)

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
    return jsonify(reservations)

@app.route("/update", methods=["POST"])
def update():
    try:
        id_ = int(request.form.get("id"))
    except (TypeError, ValueError):
        return jsonify({"status": "invalid id"}), 400
    field = request.form.get("field")   # "called" or "completed"
    value = request.form.get("value")   # "1" = True, "0" = False
    if field not in ("called", "ready", "completed"):
        return jsonify({"status": "invalid field"}), 400
    bool_value = (value == "1")
    for slot in SLOTS:
        for r in reservations[slot]:
            if r["id"] == id_:
                r[field] = bool_value
                # 完了を取り消した場合は called も一緒にリセット
                if field == "completed" and not bool_value:
                    r["called"] = False
                    r["ready"] = False
                return jsonify({"status": "ok"})
    return jsonify({"status": "not found"}), 404

@app.route("/store_action", methods=["POST"])
def store_action():
    number = request.form.get("number")
    password = request.form.get("password")
    try:
        number = int(number)
    except (TypeError, ValueError):
        return jsonify({"status": "error"})
    for slot in SLOTS:
        for r in reservations[slot]:
            if r["id"] == number and r["password"] == password:
                r["completed"] = True
                return jsonify({"status": "ok"})
    return jsonify({"status": "error"})

if __name__ == "__main__":
    app.run(debug=True, port=5000)
