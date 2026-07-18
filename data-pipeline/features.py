"""
Convierte los datos crudos de Supabase (matches + match_draft + match_player_stats)
en:
  1) un DataFrame de entrenamiento (una fila por partida, con listas de hero_ids
     de cada bando y el resultado), y
  2) la tabla derivada hero_meta_by_patch (rol/lane dominante y winrate por
     héroe y parche), que se recalcula desde cero en cada reentrenamiento.
"""
import pandas as pd
from supabase_client import get_client


def load_matches_df() -> pd.DataFrame:
    client = get_client()
    rows = []
    page = 0
    page_size = 1000
    while True:
        res = (
            client.table("matches")
            .select("match_id, patch_number, tier, radiant_win, start_time")
            .range(page * page_size, (page + 1) * page_size - 1)
            .execute()
        )
        batch = res.data
        if not batch:
            break
        rows.extend(batch)
        page += 1
    return pd.DataFrame(rows)


def load_draft_df() -> pd.DataFrame:
    client = get_client()
    rows = []
    page = 0
    page_size = 1000
    while True:
        res = (
            client.table("match_draft")
            .select("match_id, hero_id, team, is_pick")
            .range(page * page_size, (page + 1) * page_size - 1)
            .execute()
        )
        batch = res.data
        if not batch:
            break
        rows.extend(batch)
        page += 1
    return pd.DataFrame(rows)


def build_training_table(min_patch: str | None = None) -> pd.DataFrame:
    """
    Devuelve un DataFrame con una fila por partida:
        match_id, patch_number, start_time, radiant_win,
        radiant_heroes (list[int] de 5), dire_heroes (list[int] de 5)
    Descarta partidas donde el draft no tenga exactamente 5 picks por bando
    (drafts incompletos por errores de parseo, remakes, etc.)
    """
    matches = load_matches_df()
    draft = load_draft_df()

    picks = draft[draft["is_pick"]]

    def hero_list(group):
        return sorted(group["hero_id"].tolist())

    radiant_picks = (
        picks[picks["team"] == "radiant"]
        .groupby("match_id")
        .apply(hero_list, include_groups=False)
        .rename("radiant_heroes")
    )
    dire_picks = (
        picks[picks["team"] == "dire"]
        .groupby("match_id")
        .apply(hero_list, include_groups=False)
        .rename("dire_heroes")
    )

    df = matches.set_index("match_id").join(radiant_picks).join(dire_picks)
    df = df.dropna(subset=["radiant_heroes", "dire_heroes"])
    df = df[df["radiant_heroes"].apply(len) == 5]
    df = df[df["dire_heroes"].apply(len) == 5]

    if min_patch is not None:
        df = df[df["patch_number"].astype(float) >= float(min_patch)]

    return df.reset_index()


def compute_hero_meta_by_patch(draft_df: pd.DataFrame, stats_df: pd.DataFrame,
                                matches_df: pd.DataFrame) -> pd.DataFrame:
    """
    Recalcula pick rate / ban rate / win rate / lane y rol dominante por
    héroe y parche. Se sube a hero_meta_by_patch para que la API pueda
    mostrar contexto ("este héroe se juega X% como offlane en el parche actual").
    """
    merged = draft_df.merge(
        matches_df[["match_id", "patch_number", "tier", "radiant_win"]],
        on="match_id",
    )
    merged["team_won"] = (
        (merged["team"] == "radiant") & merged["radiant_win"]
    ) | ((merged["team"] == "dire") & ~merged["radiant_win"])

    picks = merged[merged["is_pick"]]
    bans = merged[~merged["is_pick"]]

    games_per_patch = matches_df.groupby(["patch_number", "tier"]).size()

    pick_counts = picks.groupby(["hero_id", "patch_number", "tier"]).size()
    win_counts = picks[picks["team_won"]].groupby(["hero_id", "patch_number", "tier"]).size()
    ban_counts = bans.groupby(["hero_id", "patch_number", "tier"]).size()

    lane_mode = (
        stats_df.groupby(["hero_id", "patch_number", "tier"])["lane"]
        .agg(lambda s: s.mode().iat[0] if not s.mode().empty else None)
    )
    role_mode = (
        stats_df.groupby(["hero_id", "patch_number", "tier"])["role"]
        .agg(lambda s: s.mode().iat[0] if not s.mode().empty else None)
    )

    out = pick_counts.rename("games_played").to_frame()
    out["wins"] = win_counts
    out["wins"] = out["wins"].fillna(0)
    out = out.join(ban_counts.rename("ban_count"))
    out["ban_count"] = out["ban_count"].fillna(0)
    out = out.join(lane_mode.rename("dominant_lane"))
    out = out.join(role_mode.rename("dominant_role"))

    out = out.reset_index()
    out["win_rate"] = out["wins"] / out["games_played"]
    out["pick_rate"] = out.apply(
        lambda r: r["games_played"] / games_per_patch.get((r["patch_number"], r["tier"]), 1),
        axis=1,
    )
    out["ban_rate"] = out.apply(
        lambda r: r["ban_count"] / games_per_patch.get((r["patch_number"], r["tier"]), 1),
        axis=1,
    )
    return out[[
        "hero_id", "patch_number", "tier", "games_played", "wins",
        "pick_rate", "ban_rate", "win_rate", "dominant_lane", "dominant_role",
    ]]
