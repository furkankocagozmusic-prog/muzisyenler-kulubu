import time
import os

from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from flask_socketio import SocketIO, emit, join_room
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3, os, re
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "musicians.db")

app = Flask(__name__)
app.config['MUSIC_UPLOAD_FOLDER'] = os.path.join(app.root_path, 'static', 'music')
os.makedirs(app.config['MUSIC_UPLOAD_FOLDER'], exist_ok=True)
app.config['UPLOAD_FOLDER'] = os.path.join(app.root_path, 'static', 'uploads')
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "local-musicians-club-secret")
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

ROOMS = [
    ("genel", "Genel Sohbet"),
    ("gitar", "Gitaristler"),
    ("davul", "Davulcular"),
    ("vokal", "Vokalistler"),
    ("klavye", "Klavye & Piyano"),
    ("grup", "Grup Arıyorum"),
    ("beste", "Beste & Şarkı Yazımı"),
    ("kayit", "Kayıt & Mix"),
    ("sahne", "Sahne & Konser"),
]

online = {}  # sid -> user_id

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = db()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        instrument TEXT DEFAULT '',
        genre TEXT DEFAULT '',
        city TEXT DEFAULT '',
        bio TEXT DEFAULT '',
        role TEXT DEFAULT 'user',
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        room TEXT NOT NULL,
        user_id INTEGER NOT NULL,
        text TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS direct_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sender_id INTEGER NOT NULL,
        receiver_id INTEGER NOT NULL,
        text TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(sender_id) REFERENCES users(id),
        FOREIGN KEY(receiver_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS listings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        description TEXT NOT NULL,
        instrument TEXT DEFAULT '',
        genre TEXT DEFAULT '',
        city TEXT DEFAULT '',
        type TEXT DEFAULT 'Müzisyen Arıyorum',
        created_at TEXT NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id)
    );
    """)
    try:
        conn.execute("ALTER TABLE users ADD COLUMN role TEXT DEFAULT 'user'")
        conn.commit()
    except sqlite3.OperationalError:
        pass
    conn.commit()
    conn.close()

def current_user():
    uid = session.get("user_id")
    if not uid:
        return None
    conn = db()
    user = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    conn.close()
    return user

def safe_text(value, max_len=1000):
    value = (value or "").strip()
    value = re.sub(r"\s+", " ", value)
    return value[:max_len]

def online_users():
    ids = list(set(online.values()))
    if not ids:
        return []
    conn = db()
    placeholders = ",".join("?" for _ in ids)
    rows = conn.execute(
        f"SELECT id, username, instrument, genre, city FROM users WHERE id IN ({placeholders}) ORDER BY username",
        ids
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def ensure_profile_photo_columns():
    with get_db() as db:
        for col in ["avatar_url", "cover_url"]:
            try:
                db.execute(f"ALTER TABLE users ADD COLUMN {col} TEXT")
            except sqlite3.OperationalError:
                pass
        db.commit()


def ensure_tracks_table():
    with get_db() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS tracks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                filename TEXT NOT NULL,
                original_name TEXT DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        """)
        db.commit()

@app.route("/")
def index():
    user = current_user()
    if not user:
        return redirect(url_for("login"))
    # sqlite3.Row doğrudan JSON'a çevrilemez; şablona normal dict gönderiyoruz.
    return render_template("index.html", user=dict(user), rooms=ROOMS)

@app.route("/login", methods=["GET", "POST"])
def login():
    error = ""
    if request.method == "POST":
        identifier = safe_text(request.form.get("identifier"), 120)
        password = request.form.get("password", "")
        conn = db()
        user = conn.execute(
            "SELECT * FROM users WHERE username=? OR email=?",
            (identifier, identifier)
        ).fetchone()
        conn.close()
        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = user["id"]
            return redirect(url_for("index"))
        error = "Kullanıcı adı/e-posta veya şifre hatalı."
    return render_template("auth.html", mode="login", error=error)

@app.route("/register", methods=["GET", "POST"])
def register():
    error = ""
    if request.method == "POST":
        username = safe_text(request.form.get("username"), 40)
        email = safe_text(request.form.get("email"), 120).lower()
        password = request.form.get("password", "")
        instrument = safe_text(request.form.get("instrument"), 80)
        genre = safe_text(request.form.get("genre"), 80)
        city = safe_text(request.form.get("city"), 80)
        bio = safe_text(request.form.get("bio"), 500)

        if len(username) < 3 or len(password) < 6 or "@" not in email:
            error = "Kullanıcı adı en az 3, şifre en az 6 karakter olmalı."
        else:
            conn = db()
            try:
                count = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]
                role = "admin" if count == 0 else "user"
                cur = conn.execute(
                    """INSERT INTO users
                    (username,email,password_hash,instrument,genre,city,bio,role,created_at)
                    VALUES (?,?,?,?,?,?,?,?,?)"""
                    , (username, email, generate_password_hash(password),
                     instrument, genre, city, bio, role, datetime.utcnow().isoformat())
                )
                conn.commit()
                session["user_id"] = cur.lastrowid
                return redirect(url_for("index"))
            except sqlite3.IntegrityError:
                error = "Bu kullanıcı adı veya e-posta zaten kayıtlı."
            finally:
                conn.close()
    return render_template("auth.html", mode="register", error=error)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/profile", methods=["POST"])
def profile():
    user = current_user()
    if not user:
        return jsonify({"ok": False}), 401
    instrument = safe_text(request.form.get("instrument"), 80)
    genre = safe_text(request.form.get("genre"), 80)
    city = safe_text(request.form.get("city"), 80)
    bio = safe_text(request.form.get("bio"), 500)
    conn = db()
    conn.execute(
        "UPDATE users SET instrument=?, genre=?, city=?, bio=? WHERE id=?",
        (instrument, genre, city, bio, user["id"])
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

@app.route("/api/search")
def search():
    if not current_user():
        return jsonify([])
    q = safe_text(request.args.get("q"), 80)
    conn = db()
    if q:
        like = f"%{q}%"
        rows = conn.execute("""
            SELECT id, username, instrument, genre, city, bio
            FROM users
            WHERE username LIKE ? OR instrument LIKE ? OR genre LIKE ? OR city LIKE ?
            ORDER BY username LIMIT 50
        """, (like, like, like, like)).fetchall()
    else:
        rows = conn.execute("""
            SELECT id, username, instrument, genre, city, bio
            FROM users ORDER BY username LIMIT 50
        """).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route("/api/messages/<room>")
def messages(room):
    if not current_user():
        return jsonify([])
    allowed = {r[0] for r in ROOMS}
    if room not in allowed:
        return jsonify([])
    conn = db()
    rows = conn.execute("""
        SELECT m.id, m.text, m.created_at, u.id AS user_id, u.username
        FROM messages m JOIN users u ON u.id=m.user_id
        WHERE m.room=? ORDER BY m.id DESC LIMIT 80
    """, (room,)).fetchall()
    conn.close()
    return jsonify([dict(r) for r in reversed(rows)])

@app.route("/api/dm/<int:other_id>")
def direct_messages(other_id):
    me = current_user()
    if not me:
        return jsonify([]), 401
    conn = db()
    rows = conn.execute("""
        SELECT d.id, d.text, d.created_at, d.sender_id, d.receiver_id,
               u.username AS sender_username
        FROM direct_messages d
        JOIN users u ON u.id=d.sender_id
        WHERE (d.sender_id=? AND d.receiver_id=?)
           OR (d.sender_id=? AND d.receiver_id=?)
        ORDER BY d.id ASC LIMIT 100
    """, (me["id"], other_id, other_id, me["id"])).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])



@app.route("/admin")
def admin():
    user = current_user()
    if not user:
        return redirect(url_for("login"))
    if user["role"] != "admin":
        return "Yetkisiz erişim", 403
    return render_template("admin.html", user=user)

@app.route("/api/admin/users")
def admin_users():
    user = current_user()
    if not user or user["role"] != "admin":
        return jsonify({"ok": False}), 403
    conn = db()
    rows = conn.execute("""
        SELECT id, username, email, instrument, genre, city, role, created_at
        FROM users ORDER BY id DESC
    """).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route("/api/admin/users/<int:user_id>/role", methods=["POST"])
def admin_change_role(user_id):
    user = current_user()
    if not user or user["role"] != "admin":
        return jsonify({"ok": False}), 403
    role = safe_text(request.form.get("role"), 20)
    if role not in ("admin", "user"):
        return jsonify({"ok": False}), 400
    if user_id == user["id"] and role != "admin":
        return jsonify({"ok": False, "error": "Kendi admin yetkini kaldıramazsın."}), 400
    conn = db()
    conn.execute("UPDATE users SET role=? WHERE id=?", (role, user_id))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

@app.route("/api/admin/users/<int:user_id>", methods=["DELETE"])
def admin_delete_user(user_id):
    user = current_user()
    if not user or user["role"] != "admin":
        return jsonify({"ok": False}), 403
    if user_id == user["id"]:
        return jsonify({"ok": False, "error": "Kendi hesabını silemezsin."}), 400
    conn = db()
    conn.execute("DELETE FROM direct_messages WHERE sender_id=? OR receiver_id=?", (user_id, user_id))
    conn.execute("DELETE FROM messages WHERE user_id=?", (user_id,))
    conn.execute("DELETE FROM listings WHERE user_id=?", (user_id,))
    conn.execute("DELETE FROM users WHERE id=?", (user_id,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

@app.route("/api/admin/listings")
def admin_listings():
    user = current_user()
    if not user or user["role"] != "admin":
        return jsonify({"ok": False}), 403
    conn = db()
    rows = conn.execute("""
        SELECT l.*, u.username
        FROM listings l JOIN users u ON u.id=l.user_id
        ORDER BY l.id DESC LIMIT 200
    """).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route("/api/admin/listings/<int:listing_id>", methods=["DELETE"])
def admin_delete_listing(listing_id):
    user = current_user()
    if not user or user["role"] != "admin":
        return jsonify({"ok": False}), 403
    conn = db()
    conn.execute("DELETE FROM listings WHERE id=?", (listing_id,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

@app.route("/api/listings", methods=["GET", "POST"])
def listings():
    user = current_user()
    if not user:
        return jsonify([]), 401
    conn = db()
    if request.method == "POST":
        title = safe_text(request.form.get("title"), 100)
        description = safe_text(request.form.get("description"), 700)
        instrument = safe_text(request.form.get("instrument"), 80)
        genre = safe_text(request.form.get("genre"), 80)
        city = safe_text(request.form.get("city"), 80)
        kind = safe_text(request.form.get("type"), 40) or "Müzisyen Arıyorum"
        if not title or not description:
            conn.close()
            return jsonify({"ok": False, "error": "Başlık ve açıklama gerekli."}), 400
        cur = conn.execute("""
            INSERT INTO listings(user_id,title,description,instrument,genre,city,type,created_at)
            VALUES(?,?,?,?,?,?,?,?)
        """, (user["id"], title, description, instrument, genre, city, kind, datetime.utcnow().isoformat()))
        conn.commit()
        lid = cur.lastrowid
        conn.close()
        return jsonify({"ok": True, "id": lid})

    rows = conn.execute("""
        SELECT l.*, u.username, u.instrument AS user_instrument
        FROM listings l JOIN users u ON u.id=l.user_id
        ORDER BY l.id DESC LIMIT 80
    """).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route("/api/listings/<int:listing_id>", methods=["DELETE"])
def delete_listing(listing_id):
    user = current_user()
    if not user:
        return jsonify({"ok": False}), 401
    conn = db()
    row = conn.execute("SELECT user_id FROM listings WHERE id=?", (listing_id,)).fetchone()
    if not row or row["user_id"] != user["id"]:
        conn.close()
        return jsonify({"ok": False}), 403
    conn.execute("DELETE FROM listings WHERE id=?", (listing_id,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

@socketio.on("connect")
def connected():
    user = current_user()
    if not user:
        return False
    online[request.sid] = user["id"]
    emit("online_users", online_users(), broadcast=True)

@socketio.on("disconnect")
def disconnected():
    online.pop(request.sid, None)
    emit("online_users", online_users(), broadcast=True)

@socketio.on("join_room")
def handle_join(data):
    user = current_user()
    if not user:
        return
    room = safe_text((data or {}).get("room"), 30)
    allowed = {r[0] for r in ROOMS}
    if room in allowed:
        join_room(room)
        emit("joined", {"room": room})

@socketio.on("send_message")
def handle_message(data):
    user = current_user()
    if not user:
        return
    room = safe_text((data or {}).get("room"), 30)
    text = safe_text((data or {}).get("text"), 1000)
    allowed = {r[0] for r in ROOMS}
    if room not in allowed or not text:
        return
    now = datetime.utcnow().isoformat()
    conn = db()
    cur = conn.execute(
        "INSERT INTO messages(room,user_id,text,created_at) VALUES(?,?,?,?)",
        (room, user["id"], text, now)
    )
    conn.commit()
    msg_id = cur.lastrowid
    conn.close()
    emit("new_message", {
        "id": msg_id, "room": room, "text": text,
        "created_at": now, "user_id": user["id"], "username": user["username"]
    }, to=room)

@socketio.on("private_message")
def handle_private(data):
    sender = current_user()
    if not sender:
        return
    try:
        receiver_id = int((data or {}).get("receiver_id"))
    except (TypeError, ValueError):
        return
    text = safe_text((data or {}).get("text"), 1000)
    if not text or receiver_id == sender["id"]:
        return
    conn = db()
    receiver = conn.execute("SELECT id, username FROM users WHERE id=?", (receiver_id,)).fetchone()
    if not receiver:
        conn.close()
        return
    now = datetime.utcnow().isoformat()
    cur = conn.execute(
        "INSERT INTO direct_messages(sender_id,receiver_id,text,created_at) VALUES(?,?,?,?)",
        (sender["id"], receiver_id, text, now)
    )
    conn.commit()
    dm_id = cur.lastrowid
    conn.close()

    payload = {
        "id": dm_id, "sender_id": sender["id"], "receiver_id": receiver_id,
        "text": text, "created_at": now, "sender_username": sender["username"]
    }
    target_sids = [sid for sid, uid in online.items() if uid == receiver_id]
    for sid in target_sids:
        emit("private_message", payload, to=sid)
    emit("private_message", payload)

if __name__ == "__main__":
    init_db()
    print("Müzisyenler Kulübü çalışıyor: http://127.0.0.1:5000")
    socketio.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False, allow_unsafe_werkzeug=True)


@app.get("/api/explore")
@login_required
def explore_users():
    q = request.args.get("q", "").strip()
    instrument = request.args.get("instrument", "").strip()
    city = request.args.get("city", "").strip()
    genre = request.args.get("genre", "").strip()

    sql = """SELECT id, username, instrument, genre, city, bio, avatar_url, cover_url
             FROM users WHERE 1=1"""
    params = []

    if q:
        sql += " AND (username LIKE ? OR bio LIKE ?)"
        like = f"%{q}%"
        params += [like, like]
    if instrument:
        sql += " AND instrument LIKE ?"
        params.append(f"%{instrument}%")
    if city:
        sql += " AND city LIKE ?"
        params.append(f"%{city}%")
    if genre:
        sql += " AND genre LIKE ?"
        params.append(f"%{genre}%")

    limit = request.args.get("limit", "100")
    try:
        limit = max(1, min(int(limit), 100))
    except ValueError:
        limit = 100
    sql += " ORDER BY username COLLATE NOCASE ASC LIMIT ?"

    with get_db() as db:
        rows = db.execute(sql, params + [limit]).fetchall()

    return jsonify({"users": [dict(r) for r in rows]})


@app.get("/api/profile/<int:user_id>")
@login_required
def public_profile(user_id):
    with get_db() as db:
        row = db.execute("""
            SELECT id, username, instrument, genre, city, bio, role, created_at, avatar_url, cover_url
            FROM users WHERE id=?
        """, (user_id,)).fetchone()
        if not row:
            return jsonify({"error": "Müzisyen bulunamadı"}), 404
    return jsonify({"user": dict(row)})


@app.route("/api/me/profile", methods=["PUT"])
@login_required
def update_my_profile():
    data = request.get_json(silent=True) or {}
    instrument = str(data.get("instrument", "")).strip()[:80]
    genre = str(data.get("genre", "")).strip()[:120]
    city = str(data.get("city", "")).strip()[:100]
    bio = str(data.get("bio", "")).strip()[:500]

    with get_db() as db:
        db.execute("""
            UPDATE users
            SET instrument=?, genre=?, city=?, bio=?
            WHERE id=?
        """, (instrument, genre, city, bio, session["user_id"]))
        db.commit()
        row = db.execute("""
            SELECT id, username, email, instrument, genre, city, bio, role, created_at
            FROM users WHERE id=?
        """, (session["user_id"],)).fetchone()
    return jsonify({"user": dict(row)})


@app.route("/api/me/photos", methods=["POST"])
@login_required
def upload_profile_photos():
    upload_dir = app.config["UPLOAD_FOLDER"]
    os.makedirs(upload_dir, exist_ok=True)

    avatar = request.files.get("avatar")
    cover = request.files.get("cover")

    allowed = {"png", "jpg", "jpeg", "webp", "gif"}

    def save_image(file, prefix):
        if not file or not file.filename:
            return None
        ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
        if ext not in allowed:
            raise ValueError("Sadece PNG, JPG, JPEG, WEBP veya GIF yükleyebilirsin.")
        filename = f"user_{session['user_id']}_{prefix}.{ext}"
        path = os.path.join(upload_dir, filename)
        file.save(path)
        return "/static/uploads/" + filename

    try:
        avatar_url = save_image(avatar, "avatar")
        cover_url = save_image(cover, "cover")
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    with get_db() as db:
        if avatar_url:
            db.execute("UPDATE users SET avatar_url=? WHERE id=?", (avatar_url, session["user_id"]))
        if cover_url:
            db.execute("UPDATE users SET cover_url=? WHERE id=?", (cover_url, session["user_id"]))
        db.commit()
        row = db.execute("""
            SELECT id, username, instrument, genre, city, bio, role, created_at, avatar_url, cover_url
            FROM users WHERE id=?
        """, (session["user_id"],)).fetchone()

    return jsonify({"user": dict(row)})



def ensure_track_engagement_tables():
    with get_db() as db:
        db.execute("CREATE TABLE IF NOT EXISTS track_likes (id INTEGER PRIMARY KEY AUTOINCREMENT, track_id INTEGER NOT NULL, user_id INTEGER NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP, UNIQUE(track_id,user_id))")
        db.execute("CREATE TABLE IF NOT EXISTS track_comments (id INTEGER PRIMARY KEY AUTOINCREMENT, track_id INTEGER NOT NULL, user_id INTEGER NOT NULL, body TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
        db.execute("CREATE TABLE IF NOT EXISTS track_plays (id INTEGER PRIMARY KEY AUTOINCREMENT, track_id INTEGER NOT NULL, user_id INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
        db.commit()

@app.route("/api/tracks", methods=["GET", "POST"])
@login_required
def tracks_api():
    if request.method == "GET":
        user_id = request.args.get("user_id", type=int)
        with get_db() as db:
            if user_id:
                rows = db.execute("""
                    SELECT t.*, u.username,
                      (SELECT COUNT(*) FROM track_likes l WHERE l.track_id=t.id) AS likes,
                      (SELECT COUNT(*) FROM track_plays p WHERE p.track_id=t.id) AS plays,
                      EXISTS(SELECT 1 FROM track_likes ml WHERE ml.track_id=t.id AND ml.user_id=?) AS liked
                    FROM tracks t JOIN users u ON u.id=t.user_id
                    WHERE t.user_id=? ORDER BY t.id DESC
                """, (session["user_id"], user_id)).fetchall()
            else:
                rows = db.execute("""
                    SELECT t.*, u.username,
                      (SELECT COUNT(*) FROM track_likes l WHERE l.track_id=t.id) AS likes,
                      (SELECT COUNT(*) FROM track_plays p WHERE p.track_id=t.id) AS plays,
                      EXISTS(SELECT 1 FROM track_likes ml WHERE ml.track_id=t.id AND ml.user_id=?) AS liked
                    FROM tracks t JOIN users u ON u.id=t.user_id
                    ORDER BY t.id DESC LIMIT 50
                """).fetchall()
        return jsonify({"tracks": [dict(r) for r in rows]})

    title = (request.form.get("title") or "").strip()[:120]
    description = (request.form.get("description") or "").strip()[:500]
    audio = request.files.get("audio")
    if not title or not audio or not audio.filename:
        return jsonify({"error": "Başlık ve ses dosyası gerekli."}), 400

    allowed = {"mp3", "wav", "m4a", "ogg", "webm"}
    ext = audio.filename.rsplit(".", 1)[-1].lower() if "." in audio.filename else ""
    if ext not in allowed:
        return jsonify({"error": "MP3, WAV, M4A, OGG veya WEBM yükleyebilirsin."}), 400

    filename = f"track_{session['user_id']}_{int(time.time()*1000)}.{ext}"
    audio.save(os.path.join(app.config["MUSIC_UPLOAD_FOLDER"], filename))

    with get_db() as db:
        cur = db.execute("""
            INSERT INTO tracks(user_id,title,description,filename,original_name)
            VALUES(?,?,?,?,?)
        """, (session["user_id"], title, description, filename, audio.filename))
        db.commit()
        track_id = cur.lastrowid

    return jsonify({"ok": True, "id": track_id, "url": "/static/music/" + filename})

@app.post("/api/tracks/<int:track_id>/like")
@login_required
def like_track(track_id):
    with get_db() as db:
        row=db.execute("SELECT id FROM track_likes WHERE track_id=? AND user_id=?",(track_id,session["user_id"])).fetchone()
        if row:
            db.execute("DELETE FROM track_likes WHERE id=?",(row["id"],)); liked=False
        else:
            db.execute("INSERT OR IGNORE INTO track_likes(track_id,user_id) VALUES(?,?)",(track_id,session["user_id"])); liked=True
        db.commit(); count=db.execute("SELECT COUNT(*) c FROM track_likes WHERE track_id=?",(track_id,)).fetchone()["c"]
    return jsonify({"liked":liked,"likes":count})

@app.post("/api/tracks/<int:track_id>/play")
@login_required
def play_track(track_id):
    with get_db() as db:
        db.execute("INSERT INTO track_plays(track_id,user_id) VALUES(?,?)",(track_id,session["user_id"])); db.commit()
        count=db.execute("SELECT COUNT(*) c FROM track_plays WHERE track_id=?",(track_id,)).fetchone()["c"]
    return jsonify({"plays":count})

@app.get("/api/tracks/<int:track_id>/comments")
@login_required
def get_track_comments(track_id):
    with get_db() as db:
        rows=db.execute("SELECT c.id,c.body,c.created_at,u.username FROM track_comments c JOIN users u ON u.id=c.user_id WHERE c.track_id=? ORDER BY c.id ASC",(track_id,)).fetchall()
    return jsonify({"comments":[dict(r) for r in rows]})

@app.post("/api/tracks/<int:track_id>/comments")
@login_required
def add_track_comment(track_id):
    body=str((request.get_json(silent=True) or {}).get("body","")).strip()[:500]
    if not body:return jsonify({"error":"Yorum boş olamaz."}),400
    with get_db() as db:
        cur=db.execute("INSERT INTO track_comments(track_id,user_id,body) VALUES(?,?,?)",(track_id,session["user_id"],body)); db.commit()
        row=db.execute("SELECT c.id,c.body,c.created_at,u.username FROM track_comments c JOIN users u ON u.id=c.user_id WHERE c.id=?",(cur.lastrowid,)).fetchone()
    return jsonify({"comment":dict(row)})

@app.delete("/api/tracks/<int:track_id>")
@login_required
def delete_track(track_id):
    with get_db() as db:
        row = db.execute("SELECT * FROM tracks WHERE id=?", (track_id,)).fetchone()
        if not row:
            return jsonify({"error":"Parça bulunamadı"}), 404
        if row["user_id"] != session["user_id"]:
            return jsonify({"error":"Bu parçayı silemezsin"}), 403
        db.execute("DELETE FROM tracks WHERE id=?", (track_id,))
        db.commit()
    try:
        os.remove(os.path.join(app.config["MUSIC_UPLOAD_FOLDER"], row["filename"]))
    except OSError:
        pass
    return jsonify({"ok": True})

if __name__ == "__main__":
    init_db()
    ensure_track_engagement_tables()
    print("Müzisyenler Kulübü çalışıyor: http://127.0.0.1:5000")
    socketio.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False, allow_unsafe_werkzeug=True)
