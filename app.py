"""Sofalao - Bolao da Copa 2026 (Flask + SQLite)."""
import os
import sqlite3
import threading
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from flask import (Flask, flash, g, redirect, render_template, request,
                   session, url_for)
from markupsafe import Markup, escape
from werkzeug.security import check_password_hash, generate_password_hash

import sync as sync_mod

# ----------------------------------------------------------------- config
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def load_local_env(path):
    try:
        with open(path, encoding="utf-8") as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip("'\""))
    except OSError:
        pass


load_local_env(os.path.join(BASE_DIR, ".env"))

DB_PATH = os.path.abspath(os.environ.get(
    "SOFALAO_DB_PATH", os.path.join(BASE_DIR, "sofalao.db")))
DB_DIR = os.path.dirname(DB_PATH)
TZ_LOCAL = ZoneInfo("America/Sao_Paulo")

POINTS_EXACT = 3        # acertou o placar exato
POINTS_RESULT = 1       # acertou vencedor/empate (sem placar exato)
POINTS_PENALTIES = 2    # mata-mata: acertou quem avancou nos penaltis
POINTS_CHAMPION = 10    # bonus: campeao
POINTS_TOP_SCORER = 10  # bonus: artilheiro

SYNC_INTERVAL_MIN = int(os.environ.get("SOFALAO_SYNC_MIN", "30"))

app = Flask(
    __name__,
    template_folder=os.environ.get("SOFALAO_TEMPLATE_DIR", "templates"),
    static_folder=os.environ.get("SOFALAO_STATIC_DIR", "static"),
)
app.secret_key = os.environ.get("SOFALAO_SECRET", "troque-esta-chave")


# ----------------------------------------------------------------- database
def ensure_db_dir():
    if DB_DIR:
        os.makedirs(DB_DIR, exist_ok=True)


def open_db():
    ensure_db_dir()
    db = sqlite3.connect(DB_PATH, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.execute("PRAGMA busy_timeout = 30000")
    return db


def get_db():
    if "db" not in g:
        g.db = open_db()
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    is_admin INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS matches (
    id INTEGER PRIMARY KEY,
    ext_id TEXT UNIQUE,
    stage TEXT NOT NULL,
    group_name TEXT,
    home TEXT NOT NULL,
    away TEXT NOT NULL,
    kickoff_utc TEXT NOT NULL,
    home_score INTEGER,
    away_score INTEGER,
    pen_winner TEXT,
    status TEXT NOT NULL DEFAULT 'SCHEDULED'
);
CREATE TABLE IF NOT EXISTS predictions (
    user_id INTEGER NOT NULL REFERENCES users(id),
    match_id INTEGER NOT NULL REFERENCES matches(id),
    home_pred INTEGER NOT NULL,
    away_pred INTEGER NOT NULL,
    pen_winner TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, match_id)
);
CREATE TABLE IF NOT EXISTS bonus_picks (
    user_id INTEGER PRIMARY KEY REFERENCES users(id),
    champion TEXT,
    top_scorer TEXT,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS players (
    id INTEGER PRIMARY KEY,
    team TEXT NOT NULL,
    name TEXT NOT NULL,
    UNIQUE (team, name)
);
"""


def init_db():
    db = open_db()
    db.execute("PRAGMA journal_mode = WAL")
    db.executescript(SCHEMA)
    for stmt in ("ALTER TABLE matches ADD COLUMN pen_winner TEXT",
                 "ALTER TABLE predictions ADD COLUMN pen_winner TEXT"):
        try:
            db.execute(stmt)
        except sqlite3.OperationalError:
            pass  # coluna ja existe
    db.commit()
    db.close()


# ----------------------------------------------------------------- helpers
def _load_players(db):
    """Retorna {team: [player, ...]} a partir do banco. Fallback para forwards.json."""
    rows = db.execute("SELECT team, name FROM players ORDER BY team, name").fetchall()
    if not rows:
        return sync_mod.load_forwards()
    result = {}
    for r in rows:
        result.setdefault(r["team"], []).append(r["name"])
    return result


def now_utc():
    return datetime.now(timezone.utc)


def parse_utc(s):
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


def fmt_local(s):
    return parse_utc(s).astimezone(TZ_LOCAL).strftime("%d/%m %H:%M")


app.jinja_env.filters["local_dt"] = fmt_local


TEAM_FLAG_CODES = {
    "africa do sul": "ZA",
    "south africa": "ZA",
    "alemanha": "DE",
    "germany": "DE",
    "arabia saudita": "SA",
    "saudi arabia": "SA",
    "argelia": "DZ",
    "algeria": "DZ",
    "argentina": "AR",
    "australia": "AU",
    "austria": "AT",
    "belgica": "BE",
    "belgium": "BE",
    "brasil": "BR",
    "brazil": "BR",
    "cabo verde": "CV",
    "cape verde": "CV",
    "canada": "CA",
    "catar": "QA",
    "qatar": "QA",
    "colombia": "CO",
    "coreia do sul": "KR",
    "south korea": "KR",
    "korea republic": "KR",
    "costa do marfim": "CI",
    "ivory coast": "CI",
    "cote d'ivoire": "CI",
    "croacia": "HR",
    "croatia": "HR",
    "curacao": "CW",
    "bosnia-herzegovina": "BA",
    "bosnia and herzegovina": "BA",
    "cape verde islands": "CV",
    "congo dr": "CD",
    "dr congo": "CD",
    "czechia": "CZ",
    "czech republic": "CZ",
    "iraq": "IQ",
    "sweden": "SE",
    "suecia": "SE",
    "turkey": "TR",
    "turquia": "TR",
    "egito": "EG",
    "egypt": "EG",
    "equador": "EC",
    "ecuador": "EC",
    "escocia": "GB",
    "scotland": "GB",
    "espanha": "ES",
    "spain": "ES",
    "estados unidos": "US",
    "usa": "US",
    "united states": "US",
    "franca": "FR",
    "france": "FR",
    "gana": "GH",
    "ghana": "GH",
    "haiti": "HT",
    "holanda": "NL",
    "netherlands": "NL",
    "paises baixos": "NL",
    "inglaterra": "GB",
    "england": "GB",
    "ira": "IR",
    "iran": "IR",
    "italia": "IT",
    "italy": "IT",
    "japao": "JP",
    "japan": "JP",
    "jordania": "JO",
    "jordan": "JO",
    "marrocos": "MA",
    "morocco": "MA",
    "mexico": "MX",
    "noruega": "NO",
    "norway": "NO",
    "nova zelandia": "NZ",
    "new zealand": "NZ",
    "panama": "PA",
    "paraguai": "PY",
    "paraguay": "PY",
    "portugal": "PT",
    "senegal": "SN",
    "suica": "CH",
    "switzerland": "CH",
    "tunisia": "TN",
    "uruguai": "UY",
    "uruguay": "UY",
    "uzbequistao": "UZ",
    "uzbekistan": "UZ",
}


def _team_key(name):
    normalized = unicodedata.normalize("NFKD", name or "")
    ascii_name = "".join(ch for ch in normalized
                         if not unicodedata.combining(ch))
    return " ".join(ascii_name.lower().replace("-", " ").split())


def flag_code(team_name):
    return (TEAM_FLAG_CODES.get(_team_key(team_name)) or "").lower()


def flag_url(team_name):
    code = flag_code(team_name)
    if not code:
        return ""
    return f"https://flagcdn.com/w20/{code}.png"


def team_label(team_name):
    return team_name or ""


def team_badge(team_name):
    name = escape(team_name or "")
    code = flag_code(team_name)
    if not code:
        return Markup(name)
    alt = escape(f"Bandeira de {team_name}")
    src = f"https://flagcdn.com/w20/{code}.png"
    srcset = f"https://flagcdn.com/w40/{code}.png 2x"
    return Markup(
        f'<span class="team-badge">'
        f'<img class="team-flag" src="{src}" srcset="{srcset}" '
        f'width="20" height="15" alt="{alt}" loading="lazy">'
        f'<span>{name}</span>'
        f'</span>'
    )


app.jinja_env.filters["team_flag"] = flag_url
app.jinja_env.filters["team_label"] = team_label
app.jinja_env.filters["team_badge"] = team_badge


@app.route("/healthz")
def healthz():
    try:
        db = open_db()
        db.execute("SELECT 1")
        db.close()
    except sqlite3.Error as exc:
        return {"status": "error", "detail": str(exc)}, 500
    return {"status": "ok"}


def current_user():
    uid = session.get("uid")
    if not uid:
        return None
    return get_db().execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()


def login_required(fn):
    from functools import wraps

    @wraps(fn)
    def wrapper(*a, **kw):
        if not session.get("uid"):
            return redirect(url_for("login"))
        if current_user() is None:
            session.clear()
            return redirect(url_for("login"))
        return fn(*a, **kw)
    return wrapper


def match_locked(match_row):
    """Locked once kickoff time has passed or the match already started."""
    if match_row["status"] in ("IN_PLAY", "PAUSED", "FINISHED"):
        return True
    return now_utc() >= parse_utc(match_row["kickoff_utc"])


def tournament_started(db):
    row = db.execute("SELECT MIN(kickoff_utc) AS k FROM matches").fetchone()
    return bool(row["k"]) and now_utc() >= parse_utc(row["k"]) + timedelta(weeks=1)


def match_points(pred, match):
    """Points for one prediction against a finished match."""
    if match["home_score"] is None or match["away_score"] is None:
        return None
    hp, ap = pred["home_pred"], pred["away_pred"]
    hs, as_ = match["home_score"], match["away_score"]
    if hp == hs and ap == as_:
        return POINTS_EXACT
    if (hp - ap > 0 and hs - as_ > 0) or (hp - ap < 0 and hs - as_ < 0) \
            or (hp == ap and hs == as_):
        return POINTS_RESULT
    return 0


def penalty_points(pred, match):
    """Bonus do mata-mata: jogo decidido nos penaltis + palpite correto."""
    if match["pen_winner"] and pred["pen_winner"] \
            and pred["pen_winner"] == match["pen_winner"]:
        return POINTS_PENALTIES
    return 0


def compute_leaderboard(db):
    users = db.execute("SELECT * FROM users ORDER BY name").fetchall()
    matches = {m["id"]: m for m in db.execute(
        "SELECT * FROM matches WHERE status='FINISHED'").fetchall()}
    champion = sync_mod.get_meta(db, "champion")
    top_scorers = [s.strip().lower() for s in
                   (sync_mod.get_meta(db, "top_scorers") or "").split(";") if s.strip()]
    board = []
    for u in users:
        pts = exact = result = pens = 0
        for p in db.execute(
                "SELECT * FROM predictions WHERE user_id=?", (u["id"],)):
            m = matches.get(p["match_id"])
            if not m:
                continue
            score = match_points(p, m)
            if score == POINTS_EXACT:
                exact += 1
            elif score == POINTS_RESULT:
                result += 1
            pp = penalty_points(p, m)
            if pp:
                pens += 1
            pts += (score or 0) + pp
        bp = db.execute("SELECT * FROM bonus_picks WHERE user_id=?",
                        (u["id"],)).fetchone()
        bonus = 0
        if bp:
            if champion and bp["champion"] == champion:
                bonus += POINTS_CHAMPION
            if top_scorers and bp["top_scorer"] \
                    and bp["top_scorer"].strip().lower() in top_scorers:
                bonus += POINTS_TOP_SCORER
        board.append({"name": u["name"], "points": pts + bonus,
                      "exact": exact, "result": result, "pens": pens,
                      "bonus": bonus})
    board.sort(key=lambda r: (-r["points"], -r["exact"], r["name"]))
    return board


# ----------------------------------------------------------------- auth
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        password = request.form.get("password", "")
        if not name or not password:
            flash("Preencha nome e senha.")
            return redirect(url_for("register"))
        db = get_db()
        first = db.execute("SELECT COUNT(*) c FROM users").fetchone()["c"] == 0
        try:
            db.execute(
                "INSERT INTO users (name, password_hash, is_admin, created_at)"
                " VALUES (?,?,?,?)",
                (name, generate_password_hash(password), int(first),
                 now_utc().isoformat()))
            db.commit()
        except sqlite3.IntegrityError:
            flash("Esse nome ja esta em uso.")
            return redirect(url_for("register"))
        uid = db.execute("SELECT id FROM users WHERE name=?",
                         (name,)).fetchone()["id"]
        session["uid"] = uid
        if first:
            flash("Voce e o primeiro usuario e virou admin do bolao!")
        return redirect(url_for("matches"))
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        password = request.form.get("password", "")
        user = get_db().execute("SELECT * FROM users WHERE name=?",
                                (name,)).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session["uid"] = user["id"]
            return redirect(url_for("matches"))
        flash("Nome ou senha invalidos.")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ----------------------------------------------------------------- pages
@app.route("/")
@login_required
def matches():
    db = get_db()
    user = current_user()
    rows = db.execute(
        "SELECT * FROM matches ORDER BY kickoff_utc, id").fetchall()
    preds = {p["match_id"]: p for p in db.execute(
        "SELECT * FROM predictions WHERE user_id=?", (user["id"],))}
    items = []
    for m in rows:
        p = preds.get(m["id"])
        finished = p and m["status"] == "FINISHED"
        items.append({
            "m": m, "p": p,
            "locked": match_locked(m),
            "knockout": m["stage"] != "GROUP_STAGE",
            "pts": match_points(p, m) if finished else None,
            "pen_pts": penalty_points(p, m) if finished else 0,
        })
    last_sync = sync_mod.get_meta(db, "last_sync")
    return render_template("matches.html", items=items, user=user,
                           last_sync=last_sync)


@app.route("/predict/<int:match_id>", methods=["POST"])
@login_required
def predict(match_id):
    db = get_db()
    m = db.execute("SELECT * FROM matches WHERE id=?", (match_id,)).fetchone()
    if not m:
        flash("Partida nao encontrada.")
        return redirect(url_for("matches"))
    if match_locked(m):
        flash("Palpites encerrados: a partida ja comecou.")
        return redirect(url_for("matches"))
    try:
        hp = int(request.form["home_pred"])
        ap = int(request.form["away_pred"])
        assert 0 <= hp <= 99 and 0 <= ap <= 99
    except (ValueError, KeyError, AssertionError):
        flash("Placar invalido.")
        return redirect(url_for("matches"))
    pen = request.form.get("pen_winner") or None
    if pen not in (None, "HOME", "AWAY") or m["stage"] == "GROUP_STAGE":
        pen = None
    db.execute(
        "INSERT INTO predictions (user_id, match_id, home_pred, away_pred,"
        " pen_winner, updated_at) VALUES (?,?,?,?,?,?)"
        " ON CONFLICT(user_id, match_id) DO UPDATE SET"
        " home_pred=excluded.home_pred, away_pred=excluded.away_pred,"
        " pen_winner=excluded.pen_winner, updated_at=excluded.updated_at",
        (session["uid"], match_id, hp, ap, pen, now_utc().isoformat()))
    db.commit()
    flash(f"Palpite salvo: {m['home']} {hp} x {ap} {m['away']}")
    return redirect(url_for("matches"))


@app.route("/bonus", methods=["GET", "POST"])
@login_required
def bonus():
    db = get_db()
    user = current_user()
    locked = tournament_started(db)
    if request.method == "POST":
        if locked:
            flash("Bonus encerrado: prazo de 1 semana apos o inicio da Copa ja passou.")
            return redirect(url_for("bonus"))
        champion = request.form.get("champion") or None
        scorer = request.form.get("top_scorer", "").strip() or None
        db.execute(
            "INSERT INTO bonus_picks (user_id, champion, top_scorer,"
            " updated_at) VALUES (?,?,?,?)"
            " ON CONFLICT(user_id) DO UPDATE SET champion=excluded.champion,"
            " top_scorer=excluded.top_scorer, updated_at=excluded.updated_at",
            (user["id"], champion, scorer, now_utc().isoformat()))
        db.commit()
        flash("Bonus salvo!")
        return redirect(url_for("bonus"))
    pick = db.execute("SELECT * FROM bonus_picks WHERE user_id=?",
                      (user["id"],)).fetchone()
    forwards = _load_players(db)
    teams = sorted(forwards.keys())
    return render_template("bonus.html", user=user, pick=pick, teams=teams,
                           forwards=forwards, locked=locked,
                           pts_champion=POINTS_CHAMPION,
                           pts_scorer=POINTS_TOP_SCORER)


@app.route("/palpites")
@login_required
def palpites():
    db = get_db()
    users = db.execute("SELECT * FROM users ORDER BY name").fetchall()
    matches = db.execute(
        "SELECT * FROM matches ORDER BY kickoff_utc, id").fetchall()
    bonus = {r["user_id"]: r for r in db.execute("SELECT * FROM bonus_picks")}
    preds = {}
    for p in db.execute("SELECT * FROM predictions"):
        preds.setdefault(p["user_id"], {})[p["match_id"]] = p
    entries = []
    for u in users:
        bp = bonus.get(u["id"])
        user_preds = []
        for m in matches:
            p = preds.get(u["id"], {}).get(m["id"])
            if p:
                user_preds.append({"m": m, "p": p})
        entries.append({
            "user": u,
            "champion": bp["champion"] if bp else None,
            "top_scorer": bp["top_scorer"] if bp else None,
            "predictions": user_preds,
        })
    return render_template("palpites.html", user=current_user(),
                           entries=entries)


@app.route("/ranking")
@login_required
def ranking():
    db = get_db()
    return render_template("ranking.html", user=current_user(),
                           board=compute_leaderboard(db),
                           pts_exact=POINTS_EXACT, pts_result=POINTS_RESULT,
                           pts_pen=POINTS_PENALTIES)


# ----------------------------------------------------------------- admin
@app.route("/admin", methods=["GET", "POST"])
@login_required
def admin():
    db = get_db()
    user = current_user()
    if not user["is_admin"]:
        flash("Apenas o admin acessa essa pagina.")
        return redirect(url_for("matches"))
    if request.method == "POST":
        action = request.form.get("action")
        if action == "sync":
            ok, msg = sync_mod.sync_now(db)
            flash(msg)
        elif action == "add_match":
            try:
                local = datetime.strptime(request.form["kickoff"],
                                          "%Y-%m-%dT%H:%M")
                utc = local.replace(tzinfo=TZ_LOCAL).astimezone(timezone.utc)
                db.execute(
                    "INSERT INTO matches (stage, group_name, home, away,"
                    " kickoff_utc) VALUES (?,?,?,?,?)",
                    (request.form.get("stage") or "GROUP_STAGE",
                     request.form.get("group_name") or None,
                     request.form["home"].strip(), request.form["away"].strip(),
                     utc.isoformat(timespec="minutes").replace("+00:00", "")))
                db.commit()
                flash("Partida criada.")
            except (KeyError, ValueError):
                flash("Dados da partida invalidos.")
        elif action == "set_score":
            pen = request.form.get("pen_winner") or None
            if pen not in (None, "HOME", "AWAY"):
                pen = None
            db.execute(
                "UPDATE matches SET home_score=?, away_score=?, pen_winner=?,"
                " status='FINISHED' WHERE id=?",
                (int(request.form["home_score"]),
                 int(request.form["away_score"]), pen,
                 int(request.form["match_id"])))
            db.commit()
            flash("Resultado registrado.")
        elif action == "set_meta":
            sync_mod.set_meta(db, "champion",
                              request.form.get("champion", "").strip())
            sync_mod.set_meta(db, "top_scorers",
                              request.form.get("top_scorers", "").strip())
            db.commit()
            flash("Campeao/artilheiro oficiais atualizados.")
        elif action == "reset_password":
            uid = request.form.get("user_id")
            new_pw = request.form.get("new_password", "").strip()
            if uid and new_pw:
                db.execute("UPDATE users SET password_hash=? WHERE id=?",
                           (generate_password_hash(new_pw), int(uid)))
                db.commit()
                name = db.execute("SELECT name FROM users WHERE id=?",
                                  (int(uid),)).fetchone()["name"]
                flash(f"Senha de {name} resetada.")
            else:
                flash("Selecione um usuario e informe a nova senha.")
        return redirect(url_for("admin"))
    rows = db.execute("SELECT * FROM matches ORDER BY kickoff_utc").fetchall()
    users = db.execute("SELECT id, name FROM users ORDER BY name").fetchall()
    return render_template("admin.html", user=user, matches=rows, users=users,
                           token_set=bool(sync_mod.api_token()),
                           champion=sync_mod.get_meta(db, "champion") or "",
                           top_scorers=sync_mod.get_meta(db, "top_scorers") or "",
                           last_sync=sync_mod.get_meta(db, "last_sync"))


# ----------------------------------------------------------------- auto-sync
_auto_sync_started = False


def _auto_sync_loop():
    while True:
        time.sleep(SYNC_INTERVAL_MIN * 60)
        try:
            db = open_db()
            sync_mod.sync_now(db)
            db.close()
        except Exception as exc:  # never kill the thread
            print(f"[auto-sync] erro: {exc}")


def start_auto_sync():
    global _auto_sync_started
    if _auto_sync_started:
        return
    if sync_mod.api_token():
        t = threading.Thread(target=_auto_sync_loop, daemon=True)
        t.start()
        _auto_sync_started = True
        print(f"[auto-sync] ativo a cada {SYNC_INTERVAL_MIN} min")
    else:
        print("[auto-sync] desativado (defina FOOTBALL_DATA_TOKEN)")


init_db()
sync_mod.init_meta(DB_PATH)

if __name__ == "__main__":
    start_auto_sync()
    app.run(debug=True, port=int(os.environ.get("PORT", "5000")))
