"""
Cliente para OpenDota. Usamos principalmente el endpoint /explorer, que permite
correr SQL de solo-lectura contra su réplica pública de partidas profesionales.
Esto evita tener que golpear /matches/{id} miles de veces (rate limit 60/min).

Docs: https://docs.opendota.com/  (sección "Data Explorer")
"""
import time
import requests
from config import OPENDOTA_BASE_URL, OPENDOTA_API_KEY, VALID_TIERS, MIN_PATCH_NUMBER

SESSION = requests.Session()


def _params(extra: dict | None = None) -> dict:
    p = dict(extra or {})
    if OPENDOTA_API_KEY:
        p["api_key"] = OPENDOTA_API_KEY
    return p


def _get(path: str, params: dict | None = None, retries: int = 3) -> dict:
    url = f"{OPENDOTA_BASE_URL}{path}"
    for attempt in range(retries):
        resp = SESSION.get(url, params=_params(params), timeout=30)
        if resp.status_code == 429:
            # rate limited, esperar y reintentar
            time.sleep(2 ** attempt * 5)
            continue
        resp.raise_for_status()
        return resp.json()
    raise RuntimeError(f"OpenDota request failed after {retries} retries: {url}")


def explorer_query(sql: str) -> list[dict]:
    """Corre una query SQL de solo lectura contra el Data Explorer de OpenDota."""
    data = _get("/explorer", {"sql": sql})
    return data.get("rows", [])


def get_heroes() -> list[dict]:
    """Catálogo completo de héroes (id, nombre, atributo, tipo de ataque)."""
    return _get("/heroes")


def get_leagues() -> list[dict]:
    """Todas las ligas, con su tier. Filtramos tier1 en Python porque la
    cantidad de ligas es pequeña (unos pocos miles)."""
    leagues = _get("/leagues")
    return [l for l in leagues if l.get("tier") in VALID_TIERS]


def get_tier1_matches(min_patch: str = MIN_PATCH_NUMBER, limit: int = 5000,
                       offset: int = 0) -> list[dict]:
    """
    Trae partidas tier 1 desde el parche mínimo indicado, incluyendo el
    resultado y los ids de equipo. Los picks/bans se traen aparte porque
    OpenDota los guarda en una tabla relacional distinta (picks_bans).
    """
    sql = f"""
        select
            m.match_id,
            m.leagueid as league_id,
            m.patch,
            m.radiant_team_id,
            m.dire_team_id,
            m.radiant_win,
            m.start_time,
            m.duration,
            l.tier,
            l.name as league_name
        from matches m
        join leagues l on l.leagueid = m.leagueid
        where l.tier in ({', '.join(f"'{t}'" for t in VALID_TIERS)})
          and m.patch >= (
              select id from patches where patch_number = '{min_patch}'
          )
        order by m.start_time desc
        limit {limit} offset {offset};
    """
    return explorer_query(sql)


def get_picks_bans_for_matches(match_ids: list[int]) -> list[dict]:
    """Trae picks y bans para un lote de match_ids."""
    if not match_ids:
        return []
    ids_csv = ", ".join(str(m) for m in match_ids)
    sql = f"""
        select match_id, hero_id, is_pick, team, "order"
        from picks_bans
        where match_id in ({ids_csv})
        order by match_id, "order";
    """
    return explorer_query(sql)


def get_player_stats_for_matches(match_ids: list[int]) -> list[dict]:
    """Trae stats por jugador/héroe (kills, deaths, gpm, etc.) para un lote."""
    if not match_ids:
        return []
    ids_csv = ", ".join(str(m) for m in match_ids)
    sql = f"""
        select
            match_id, account_id, hero_id, player_slot,
            kills, deaths, assists, gold_per_min, xp_per_min, net_worth,
            lane, lane_role
        from player_matches
        where match_id in ({ids_csv});
    """
    return explorer_query(sql)
