-- =====================================================================
-- No Bounce — Tournaments feature
-- Run this in the Supabase SQL editor.
--
-- Conventions follow the existing schema:
--   * uuid primary keys (gen_random_uuid)
--   * created_at / updated_at timestamptz
--   * admin_created_by text (admin email)
--   * user references -> profiles.id (uuid)
--   * court references -> courts.id (uuid)
--
-- Model overview:
--   tournaments ──┬─< tournament_groups
--                 ├─< tournament_teams (group_id -> tournament_groups)
--                 │      └─< tournament_team_members (profile_id -> profiles, or guest name)
--                 └─< tournament_matches (team_a / team_b -> tournament_teams,
--                              court_id -> courts, next_match_id self-ref for brackets)
-- =====================================================================


-- ---------------------------------------------------------------------
-- Reusable trigger to keep updated_at fresh
-- ---------------------------------------------------------------------
create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;


-- ---------------------------------------------------------------------
-- 1. tournaments
-- ---------------------------------------------------------------------
create table if not exists public.tournaments (
  id            uuid primary key default gen_random_uuid(),
  name          text not null,
  description   text,

  -- default / home court for the event (matches can still override per-match)
  court_id      uuid references public.courts(id) on delete set null,

  -- 'knockout'             -> straight to elimination
  -- 'group_then_knockout'  -> group phase first, then elimination
  format        text not null default 'knockout'
                  check (format in ('knockout', 'group_then_knockout')),

  -- 1 = 1x1, 3 = 3x3, 5 = 5x5, etc.
  team_size     int not null default 5 check (team_size >= 1),

  status        text not null default 'draft'
                  check (status in ('draft','registration','group_stage','knockout','completed','cancelled')),

  max_teams     int check (max_teams is null or max_teams >= 2),
  start_date    date,
  end_date      date,

  -- group-stage scoring / qualification config
  points_win                int not null default 2,
  points_draw               int not null default 1,
  points_loss               int not null default 1,
  teams_advancing_per_group int not null default 2 check (teams_advancing_per_group >= 1),

  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),
  admin_created_by text
);

create index if not exists idx_tournaments_court_id on public.tournaments(court_id);
create index if not exists idx_tournaments_status   on public.tournaments(status);

drop trigger if exists trg_tournaments_updated_at on public.tournaments;
create trigger trg_tournaments_updated_at
  before update on public.tournaments
  for each row execute function public.set_updated_at();


-- ---------------------------------------------------------------------
-- 2. tournament_groups  (only used when format = 'group_then_knockout')
-- ---------------------------------------------------------------------
create table if not exists public.tournament_groups (
  id            uuid primary key default gen_random_uuid(),
  tournament_id uuid not null references public.tournaments(id) on delete cascade,
  name          text not null,                       -- e.g. "Grupo A"
  created_at    timestamptz not null default now(),
  unique (tournament_id, name)
);

create index if not exists idx_groups_tournament_id on public.tournament_groups(tournament_id);


-- ---------------------------------------------------------------------
-- 3. tournament_teams  (per-tournament)
-- ---------------------------------------------------------------------
create table if not exists public.tournament_teams (
  id            uuid primary key default gen_random_uuid(),
  tournament_id uuid not null references public.tournaments(id) on delete cascade,
  name          text not null,
  logo_url      text,
  seed          int,                                  -- optional knockout seeding
  group_id      uuid references public.tournament_groups(id) on delete set null,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),
  admin_created_by text,
  unique (tournament_id, name)
);

create index if not exists idx_tournament_teams_tournament_id on public.tournament_teams(tournament_id);
create index if not exists idx_tournament_teams_group_id       on public.tournament_teams(group_id);

drop trigger if exists trg_tournament_teams_updated_at on public.tournament_teams;
create trigger trg_tournament_teams_updated_at
  before update on public.tournament_teams
  for each row execute function public.set_updated_at();


-- ---------------------------------------------------------------------
-- 4. tournament_team_members  (roster — app users via profile_id, or guests via name)
-- ---------------------------------------------------------------------
create table if not exists public.tournament_team_members (
  id            uuid primary key default gen_random_uuid(),
  team_id       uuid not null references public.tournament_teams(id) on delete cascade,
  profile_id    uuid references public.profiles(id) on delete set null,
  player_name   text,                                 -- used for non-app (guest) players
  jersey_number int,
  is_captain    boolean not null default false,
  created_at    timestamptz not null default now(),

  -- must identify the player one way or another
  constraint tournament_team_member_identity check (profile_id is not null or player_name is not null)
);

create index if not exists idx_tournament_team_members_team_id    on public.tournament_team_members(team_id);
create index if not exists idx_tournament_team_members_profile_id on public.tournament_team_members(profile_id);

-- a given app user can't be added to the same team twice
create unique index if not exists uq_tournament_team_members_team_profile
  on public.tournament_team_members(team_id, profile_id)
  where profile_id is not null;


-- ---------------------------------------------------------------------
-- 5. tournament_matches  (both group and knockout games)
--    team_a / team_b instead of home / away (single-court tournaments)
-- ---------------------------------------------------------------------
create table if not exists public.tournament_matches (
  id            uuid primary key default gen_random_uuid(),
  tournament_id uuid not null references public.tournaments(id) on delete cascade,

  stage         text not null check (stage in ('group','knockout')),
  group_id      uuid references public.tournament_groups(id) on delete cascade, -- group matches only

  round         int,                                  -- knockout round (1 = first) or group matchday
  round_label   text,                                 -- e.g. "Final", "Meia-final", "Quartos"
  bracket_position int,                               -- ordering within a knockout round

  team_a_id     uuid references public.tournament_teams(id) on delete set null, -- nullable: TBD bracket slot
  team_b_id     uuid references public.tournament_teams(id) on delete set null,
  score_a       int,
  score_b       int,
  winner_team_id uuid references public.tournament_teams(id) on delete set null,

  court_id      uuid references public.courts(id) on delete set null,
  scheduled_at  timestamptz,

  status        text not null default 'scheduled'
                  check (status in ('scheduled','in_progress','completed','cancelled')),

  -- knockout progression: winner of this match advances into next_match_id
  next_match_id uuid references public.tournament_matches(id) on delete set null,

  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),
  admin_created_by text,

  constraint tournament_matches_distinct_teams
    check (team_a_id is null or team_b_id is null or team_a_id <> team_b_id)
);

create index if not exists idx_tournament_matches_tournament_id on public.tournament_matches(tournament_id);
create index if not exists idx_tournament_matches_group_id      on public.tournament_matches(group_id);
create index if not exists idx_tournament_matches_team_a        on public.tournament_matches(team_a_id);
create index if not exists idx_tournament_matches_team_b        on public.tournament_matches(team_b_id);
create index if not exists idx_tournament_matches_next_match    on public.tournament_matches(next_match_id);

drop trigger if exists trg_tournament_matches_updated_at on public.tournament_matches;
create trigger trg_tournament_matches_updated_at
  before update on public.tournament_matches
  for each row execute function public.set_updated_at();


-- ---------------------------------------------------------------------
-- 6. Group standings (computed view — always consistent with matches)
-- ---------------------------------------------------------------------
create or replace view public.tournament_group_standings as
with team_rows as (
  -- one row per team per completed group match, from that team's perspective
  select
    m.tournament_id,
    m.group_id,
    m.team_a_id as team_id,
    m.score_a   as score_for,
    m.score_b   as score_against
  from public.tournament_matches m
  where m.stage = 'group'
    and m.status = 'completed'
    and m.team_a_id is not null
  union all
  select
    m.tournament_id,
    m.group_id,
    m.team_b_id as team_id,
    m.score_b   as score_for,
    m.score_a   as score_against
  from public.tournament_matches m
  where m.stage = 'group'
    and m.status = 'completed'
    and m.team_b_id is not null
)
select
  t.id            as team_id,
  t.tournament_id,
  t.group_id,
  t.name          as team_name,
  count(tr.team_id)::int                                              as played,
  coalesce(sum((tr.score_for >  tr.score_against)::int), 0)           as wins,
  coalesce(sum((tr.score_for =  tr.score_against)::int), 0)           as draws,
  coalesce(sum((tr.score_for <  tr.score_against)::int), 0)           as losses,
  coalesce(sum(tr.score_for), 0)::int                                 as points_for,
  coalesce(sum(tr.score_against), 0)::int                             as points_against,
  coalesce(sum(tr.score_for - tr.score_against), 0)::int              as point_diff,
  coalesce(
      sum((tr.score_for >  tr.score_against)::int) * tour.points_win
    + sum((tr.score_for =  tr.score_against)::int) * tour.points_draw
    + sum((tr.score_for <  tr.score_against)::int) * tour.points_loss
  , 0)::int                                                           as standing_points
from public.tournament_teams t
join public.tournaments tour on tour.id = t.tournament_id
left join team_rows tr on tr.team_id = t.id
where t.group_id is not null
group by t.id, t.tournament_id, t.group_id, t.name,
         tour.points_win, tour.points_draw, tour.points_loss;

-- run the view with the querying user's permissions so it honours RLS below
alter view public.tournament_group_standings set (security_invoker = true);


-- ---------------------------------------------------------------------
-- 7. Row Level Security — public read, no client writes
--    (Streamlit uses the service-role key and bypasses RLS entirely;
--     the mobile app reads with the anon/authenticated key.)
-- ---------------------------------------------------------------------
alter table public.tournaments             enable row level security;
alter table public.tournament_groups       enable row level security;
alter table public.tournament_teams        enable row level security;
alter table public.tournament_team_members enable row level security;
alter table public.tournament_matches      enable row level security;

create policy "tournaments_public_read" on public.tournaments
  for select to anon, authenticated using (true);

create policy "tournament_groups_public_read" on public.tournament_groups
  for select to anon, authenticated using (true);

create policy "tournament_teams_public_read" on public.tournament_teams
  for select to anon, authenticated using (true);

create policy "tournament_team_members_public_read" on public.tournament_team_members
  for select to anon, authenticated using (true);

create policy "tournament_matches_public_read" on public.tournament_matches
  for select to anon, authenticated using (true);
