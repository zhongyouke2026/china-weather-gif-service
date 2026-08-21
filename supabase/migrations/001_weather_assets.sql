create extension if not exists pgcrypto;

create table if not exists public.weather_assets (
  id uuid primary key default gen_random_uuid(),
  asset_key text not null default 'china-7d',
  gfs_run text not null check (gfs_run ~ '^[0-9]{10}$'),
  status text not null default 'queued'
    check (status in ('queued', 'processing', 'ready', 'failed')),
  storage_bucket text,
  storage_path text,
  content_type text,
  byte_size bigint check (byte_size is null or byte_size >= 0),
  sha256 text check (sha256 is null or sha256 ~ '^[0-9a-f]{64}$'),
  frame_count integer check (frame_count is null or frame_count > 0),
  forecast_start timestamptz,
  forecast_end timestamptz,
  generated_at timestamptz,
  queued_at timestamptz not null default now(),
  started_at timestamptz,
  finished_at timestamptz,
  updated_at timestamptz not null default now(),
  trigger_source text,
  error_message text,
  metadata jsonb not null default '{}'::jsonb,
  constraint weather_assets_asset_run_key unique (asset_key, gfs_run),
  constraint weather_assets_ready_fields check (
    status <> 'ready'
    or (
      storage_bucket is not null
      and storage_path is not null
      and generated_at is not null
      and sha256 is not null
    )
  )
);

create index if not exists weather_assets_latest_ready_idx
  on public.weather_assets (asset_key, generated_at desc)
  where status = 'ready';

create or replace function public.set_weather_assets_updated_at()
returns trigger
language plpgsql
set search_path = public
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists weather_assets_set_updated_at on public.weather_assets;
create trigger weather_assets_set_updated_at
before update on public.weather_assets
for each row execute function public.set_weather_assets_updated_at();

-- Atomically claims a run. Queued/failed rows and stale processing rows are
-- reclaimable; ready rows are never regenerated accidentally.
create or replace function public.claim_weather_generation(
  p_asset_key text,
  p_gfs_run text,
  p_trigger_source text default 'batch'
)
returns boolean
language plpgsql
security definer
set search_path = public
as $$
declare
  claimed_id uuid;
begin
  insert into public.weather_assets (
    asset_key,
    gfs_run,
    status,
    queued_at,
    started_at,
    trigger_source,
    error_message
  )
  values (
    p_asset_key,
    p_gfs_run,
    'processing',
    now(),
    now(),
    p_trigger_source,
    null
  )
  on conflict (asset_key, gfs_run) do nothing
  returning id into claimed_id;

  if claimed_id is not null then
    return true;
  end if;

  update public.weather_assets
  set
    status = 'processing',
    started_at = now(),
    finished_at = null,
    trigger_source = p_trigger_source,
    error_message = null
  where asset_key = p_asset_key
    and gfs_run = p_gfs_run
    and (
      status in ('queued', 'failed')
      or (status = 'processing' and updated_at < now() - interval '4 hours')
    )
  returning id into claimed_id;

  return claimed_id is not null;
end;
$$;

alter table public.weather_assets enable row level security;

-- All DB and Storage access is server-side with the service-role key. No
-- browser-facing RLS policy is intentionally created for this table.
revoke all on table public.weather_assets from anon, authenticated;
revoke all on function public.claim_weather_generation(text, text, text)
  from public, anon, authenticated;
grant all on table public.weather_assets to service_role;
grant execute on function public.claim_weather_generation(text, text, text)
  to service_role;

-- Private, versioned files. The Next.js route proxies the newest one.
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
  'weather-assets',
  'weather-assets',
  false,
  52428800,
  array['image/gif', 'application/json']
)
on conflict (id) do update set
  public = excluded.public,
  file_size_limit = excluded.file_size_limit,
  allowed_mime_types = excluded.allowed_mime_types;

