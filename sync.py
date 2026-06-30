"""Sync da Copa 2026.

- football-data.org: estrutura de jogos (tabela, times, fases, elencos).
- worldcup26.ir:     placares em tempo real (sem API key).

Token football-data.org: https://www.football-data.org/client/register
Defina a variavel de ambiente FOOTBALL_DATA_TOKEN.
"""
import json
import os
import sqlite3
from datetime import datetime, timezone

import requests

API_URL = "https://api.football-data.org/v4/competitions/WC/matches"
API_TEAMS_URL = "https://api.football-data.org/v4/competitions/WC/teams"
WC26_GAMES_URL = "https://worldcup26.ir/get/games"
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

STAGE_PT = {
    "GROUP_STAGE": "Fase de grupos",
    "LAST_32": "32 avos",
    "ROUND_OF_32": "32 avos",
    "LAST_16": "Oitavas",
    "ROUND_OF_16": "Oitavas",
    "QUARTER_FINALS": "Quartas",
    "SEMI_FINALS": "Semifinal",
    "THIRD_PLACE": "3o lugar",
    "FINAL": "Final",
}


def api_token():
    return os.environ.get("FOOTBALL_DATA_TOKEN", "").strip()


# ----------------------------------------------------------------- meta kv
def init_meta(db_path):
    db = sqlite3.connect(db_path)
    db.execute("CREATE TABLE IF NOT EXISTS meta"
               " (key TEXT PRIMARY KEY, value TEXT)")
    db.commit()
    db.close()


def get_meta(db, key):
    row = db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else None


def set_meta(db, key, value):
    db.execute("INSERT INTO meta (key, value) VALUES (?,?)"
               " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
               (key, value))


# ----------------------------------------------------------------- data
_ATTACKER_POSITIONS = {"Offence", "Midfield"}


def fetch_scorers(db):
    """Busca elencos da API e retorna {team_name: [player_name, ...]}."""
    token = api_token()
    if not token:
        return _load_forwards_fallback(db)
    try:
        resp = requests.get(API_TEAMS_URL, headers={"X-Auth-Token": token},
                            timeout=20)
        resp.raise_for_status()
        payload = resp.json()
    except requests.RequestException:
        return _load_forwards_fallback(db)

    result = {}
    for team in payload.get("teams", []):
        name = team.get("name") or team.get("shortName", "")
        players = [
            p["name"] for p in (team.get("squad") or [])
            if p.get("position") in _ATTACKER_POSITIONS
        ]
        if players:
            result[name] = sorted(players)
    return result


def _load_forwards_fallback(db):
    """Fallback: le forwards.json ou monta lista a partir dos times do banco."""
    path = os.path.join(BASE_DIR, "forwards.json")
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}


def load_forwards():
    """Compatibilidade: retorna forwards.json sem banco (usado em contextos sem DB)."""
    return _load_forwards_fallback(None)


def known_teams(db):
    """Selecoes conhecidas: as do banco + as do forwards.json."""
    teams = {r["home"] for r in db.execute(
        "SELECT DISTINCT home FROM matches WHERE home NOT LIKE '%definir%'")}
    teams |= {r["away"] for r in db.execute(
        "SELECT DISTINCT away FROM matches WHERE away NOT LIKE '%definir%'")}
    teams |= set(load_forwards().keys())
    return sorted(teams)


# ----------------------------------------------------------------- sync
def _sync_players_once(db, token):
    """Popula a tabela players uma unica vez (pula se ja houver dados)."""
    if db.execute("SELECT COUNT(*) FROM players").fetchone()[0] > 0:
        return ""
    try:
        resp = requests.get(API_TEAMS_URL, headers={"X-Auth-Token": token},
                            timeout=20)
        resp.raise_for_status()
        payload = resp.json()
    except requests.RequestException as exc:
        return f" (elencos: falha - {exc})"

    count = 0
    for team in payload.get("teams", []):
        name = team.get("name") or team.get("shortName", "")
        for p in (team.get("squad") or []):
            if p.get("position") in _ATTACKER_POSITIONS:
                try:
                    db.execute("INSERT OR IGNORE INTO players (team, name) VALUES (?,?)",
                               (name, p["name"]))
                    count += 1
                except Exception:
                    pass
    return f" {count} jogadores importados."


def _team_name(side):
    return (side or {}).get("name") or "A definir"


def sync_now(db):
    """Busca jogos na API e faz upsert por ext_id. Retorna (ok, mensagem)."""
    token = api_token()
    if not token:
        return False, ("Sync indisponivel: defina FOOTBALL_DATA_TOKEN "
                       "(token gratuito em football-data.org).")
    try:
        resp = requests.get(API_URL, headers={"X-Auth-Token": token},
                            timeout=20)
        resp.raise_for_status()
        payload = resp.json()
    except requests.RequestException as exc:
        return False, f"Falha ao consultar a API: {exc}"

    created = updated = 0
    for m in payload.get("matches", []):
        ext_id = str(m["id"])
        kickoff = (datetime.fromisoformat(m["utcDate"].replace("Z", "+00:00"))
                   .astimezone(timezone.utc)
                   .isoformat(timespec="minutes").replace("+00:00", ""))
        home = _team_name(m.get("homeTeam"))
        away = _team_name(m.get("awayTeam"))
        stage = m.get("stage") or "GROUP_STAGE"
        group = m.get("group")
        status = m.get("status") or "SCHEDULED"
        score = m.get("score") or {}
        pen = None
        if score.get("duration") == "PENALTY_SHOOTOUT":
            pen = {"HOME_TEAM": "HOME", "AWAY_TEAM": "AWAY"}.get(
                score.get("winner"))
            ft = score.get("regularTime") or {}
        else:
            ft = score.get("fullTime") or {}
        hs, as_ = ft.get("home"), ft.get("away")
        if status != "FINISHED":
            hs = as_ = pen = None

        row = db.execute("SELECT id FROM matches WHERE ext_id=?",
                         (ext_id,)).fetchone()
        if row:
            db.execute(
                "UPDATE matches SET stage=?, group_name=?, home=?, away=?,"
                " kickoff_utc=?, home_score=?, away_score=?, pen_winner=?,"
                " status=? WHERE ext_id=?",
                (stage, group, home, away, kickoff, hs, as_, pen, status,
                 ext_id))
            updated += 1
        else:
            db.execute(
                "INSERT INTO matches (ext_id, stage, group_name, home, away,"
                " kickoff_utc, home_score, away_score, pen_winner, status)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (ext_id, stage, group, home, away, kickoff, hs, as_, pen,
                 status))
            created += 1

    players_msg = _sync_players_once(db, token)

    _, scores_msg = sync_scores(db)

    set_meta(db, "last_sync",
             datetime.now(timezone.utc).isoformat(timespec="seconds"))
    db.commit()
    return True, (f"Sync ok: {created} partidas novas, "
                  f"{updated} atualizadas.{players_msg} {scores_msg}")


import unicodedata


def _normalize(name):
    """Normaliza nome de time para comparação fuzzy."""
    name = unicodedata.normalize("NFKD", name or "")
    name = "".join(c for c in name if not unicodedata.combining(c))
    return name.lower().replace("-", " ").strip()


def _names_match(a, b):
    na, nb = _normalize(a), _normalize(b)
    return na == nb or na in nb or nb in na


def sync_scores(db):
    """Atualiza placares usando worldcup26.ir (tempo real, sem API key).

    Faz match com as partidas do banco pelo nome dos times.
    Retorna (atualizados, msg).
    """
    try:
        resp = requests.get(WC26_GAMES_URL, timeout=15)
        resp.raise_for_status()
        games = resp.json()
    except requests.RequestException as exc:
        return 0, f"worldcup26.ir indisponivel: {exc}"

    if not isinstance(games, list):
        games = games.get("data", games.get("games", games.get("matches", [])))

    db_matches = db.execute(
        "SELECT id, home, away, status, home_score FROM matches"
        " WHERE status != 'FINISHED' OR home_score IS NULL OR pen_winner IS NULL"
    ).fetchall()

    updated = 0
    for g in games:
        if g.get("finished") != "TRUE":
            continue
        hs = g.get("home_score")
        as_ = g.get("away_score")
        if hs is None or as_ is None:
            continue
        try:
            hs, as_ = int(hs), int(as_)
        except (ValueError, TypeError):
            continue

        pen_winner = None
        try:
            hps = g.get("home_penalty_score")
            aps = g.get("away_penalty_score")
            if hps is not None and aps is not None:
                hps, aps = int(hps), int(aps)
                pen_winner = "home" if hps > aps else "away"
        except (ValueError, TypeError):
            pass

        g_home = g.get("home_team_name_en", "")
        g_away = g.get("away_team_name_en", "")

        for row in db_matches:
            if _names_match(row["home"], g_home) and _names_match(row["away"], g_away):
                already_finished = (row["status"] == "FINISHED"
                                    and row["home_score"] is not None)
                if already_finished and pen_winner is None:
                    break
                if already_finished:
                    db.execute(
                        "UPDATE matches SET pen_winner=? WHERE id=? AND pen_winner IS NULL",
                        (pen_winner, row["id"]))
                else:
                    db.execute(
                        "UPDATE matches SET home_score=?, away_score=?, pen_winner=?,"
                        " status='FINISHED' WHERE id=?",
                        (hs, as_, pen_winner, row["id"]))
                updated += 1
                break

    if updated:
        db.commit()
    return updated, f"{updated} placar(es) atualizado(s) via worldcup26.ir."


if __name__ == "__main__":
    # uso: python sync.py  (sync manual via linha de comando)
    init_meta(os.path.join(BASE_DIR, "sofalao.db"))
    conn = sqlite3.connect(os.path.join(BASE_DIR, "sofalao.db"))
    conn.row_factory = sqlite3.Row
    ok, msg = sync_now(conn)
    print(msg)
