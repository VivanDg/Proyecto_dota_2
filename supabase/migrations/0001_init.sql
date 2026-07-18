-- =========================================================
-- Dota 2 Tier-1 Match Predictor — esquema inicial
-- =========================================================
-- Diseño:
--  - "matches" guarda el resultado final y metadatos del parche/liga.
--  - "match_draft" guarda picks Y bans (aunque el modelo de producción
--    solo use picks, se conservan los bans para features futuras).
--  - "hero_meta_by_patch" es una tabla derivada (se recalcula en cada
--    reentrenamiento) con rol/lane dominante y winrate por parche,
--    para no hardcodear roles que cambian con el meta.
--  - "model_registry" lleva el historial de modelos entrenados, para
--    poder hacer rollback si un reentrenamiento empeora las métricas.
--  - "predictions_log" guarda cada predicción servida, útil para medir
--    drift real vs. resultados reales a futuro.
-- =========================================================

create table if not exists heroes (
  hero_id integer primary key,          -- id numérico de OpenDota/Valve
  internal_name text not null,          -- ej: npc_dota_hero_axe
  localized_name text not null,         -- ej: Axe
  primary_attr text,                    -- str / agi / int / all
  attack_type text                      -- melee / ranged
);

create table if not exists patches (
  patch_id serial primary key,
  patch_name text unique not null,      -- ej: '7.41'
  release_date date,
  notes text
);

create table if not exists leagues (
  league_id integer primary key,        -- leagueid de OpenDota
  name text not null,
  tier text not null check (tier in ('premium', 'professional', 'other'))
);

create table if not exists teams (
  team_id integer primary key,
  name text,
  tag text
);

create table if not exists matches (
  match_id bigint primary key,          -- match_id de OpenDota
  league_id integer references leagues(league_id),
  patch_id integer references patches(patch_id),
  patch_number text not null,           -- string cruda, ej '7.41' (redundante pero útil para queries rápidas)
  radiant_team_id integer references teams(team_id),
  dire_team_id integer references teams(team_id),
  radiant_win boolean not null,
  start_time timestamptz not null,
  duration_seconds integer,
  tier text not null check (tier in ('premium', 'professional')),
  ingested_at timestamptz default now()
);

create index if not exists idx_matches_patch on matches(patch_number);
create index if not exists idx_matches_tier on matches(tier);
create index if not exists idx_matches_start_time on matches(start_time);

-- Draft completo: picks y bans, con orden y fase (para no perder info)
create table if not exists match_draft (
  id bigserial primary key,
  match_id bigint references matches(match_id) on delete cascade,
  hero_id integer references heroes(hero_id),
  team text not null check (team in ('radiant', 'dire')),
  is_pick boolean not null,             -- true = pick, false = ban
  order_num integer,                    -- orden dentro del draft (0-based)
  unique (match_id, team, order_num, is_pick)
);

create index if not exists idx_draft_match on match_draft(match_id);
create index if not exists idx_draft_hero on match_draft(hero_id);

-- Stats por jugador/héroe en cada partida (fase 2: kills, gpm, etc.)
create table if not exists match_player_stats (
  id bigserial primary key,
  match_id bigint references matches(match_id) on delete cascade,
  account_id bigint,
  player_name text,
  hero_id integer references heroes(hero_id),
  team text not null check (team in ('radiant', 'dire')),
  lane text,                            -- safelane / midlane / offlane / jungle / roaming
  role text,                            -- carry / mid / offlane / soft_support / hard_support
  kills integer,
  deaths integer,
  assists integer,
  gpm integer,
  xpm integer,
  net_worth integer
);

create index if not exists idx_player_stats_match on match_player_stats(match_id);
create index if not exists idx_player_stats_hero on match_player_stats(hero_id);

-- Tabla derivada: rol/lane dominante y desempeño por héroe y por parche.
-- Se recalcula en cada reentrenamiento a partir de match_player_stats + match_draft.
create table if not exists hero_meta_by_patch (
  id bigserial primary key,
  hero_id integer references heroes(hero_id),
  patch_number text not null,
  tier text not null,
  games_played integer not null default 0,
  wins integer not null default 0,
  pick_rate numeric,
  ban_rate numeric,
  win_rate numeric,
  dominant_lane text,
  dominant_role text,
  computed_at timestamptz default now(),
  unique (hero_id, patch_number, tier)
);

-- Historial de modelos entrenados
create table if not exists model_registry (
  id bigserial primary key,
  version text unique not null,          -- ej: 2026-07-18T00:00Z_nn_v3
  model_type text not null,              -- 'neural_net' | 'gbm_baseline'
  trained_at timestamptz default now(),
  patch_range_min text,
  patch_range_max text,
  tier_filter text[],
  train_rows integer,
  val_rows integer,
  metrics jsonb,                         -- { accuracy, log_loss, auc, ... }
  storage_path text,                     -- ruta en Supabase Storage (bucket "models")
  is_active boolean default false
);

-- Log de predicciones servidas por la API
create table if not exists predictions_log (
  id bigserial primary key,
  created_at timestamptz default now(),
  radiant_hero_ids integer[] not null,
  dire_hero_ids integer[] not null,
  predicted_prob_radiant numeric not null,
  predicted_winner text not null check (predicted_winner in ('radiant', 'dire')),
  model_version text references model_registry(version),
  client_ip text
);

-- Solo un modelo activo a la vez por tipo
create unique index if not exists idx_one_active_model
  on model_registry (model_type)
  where is_active = true;
