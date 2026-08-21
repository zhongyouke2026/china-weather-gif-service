import { createSupabaseAdmin } from "@/lib/supabase-admin";
import { weatherAssetKey } from "@/lib/env";

export type WeatherAssetStatus =
  | "queued"
  | "processing"
  | "ready"
  | "failed";

export interface WeatherAsset {
  id: string;
  asset_key: string;
  gfs_run: string;
  status: WeatherAssetStatus;
  storage_bucket: string | null;
  storage_path: string | null;
  content_type: string | null;
  byte_size: number | null;
  sha256: string | null;
  frame_count: number | null;
  forecast_start: string | null;
  forecast_end: string | null;
  generated_at: string | null;
  queued_at: string;
  started_at: string | null;
  finished_at: string | null;
  updated_at: string;
  trigger_source: string | null;
  error_message: string | null;
  metadata: Record<string, unknown>;
}

const ASSET_COLUMNS = [
  "id",
  "asset_key",
  "gfs_run",
  "status",
  "storage_bucket",
  "storage_path",
  "content_type",
  "byte_size",
  "sha256",
  "frame_count",
  "forecast_start",
  "forecast_end",
  "generated_at",
  "queued_at",
  "started_at",
  "finished_at",
  "updated_at",
  "trigger_source",
  "error_message",
  "metadata",
].join(",");

export async function getLatestReadyAsset(): Promise<WeatherAsset | null> {
  const supabase = createSupabaseAdmin();
  const { data, error } = await supabase
    .from("weather_assets")
    .select(ASSET_COLUMNS)
    .eq("asset_key", weatherAssetKey())
    .eq("status", "ready")
    .order("generated_at", { ascending: false })
    .limit(1)
    .maybeSingle();

  if (error) {
    throw new Error(`Unable to read latest weather asset: ${error.message}`);
  }
  return (data as WeatherAsset | null) ?? null;
}

export async function getAssetForRun(
  gfsRun: string,
): Promise<WeatherAsset | null> {
  const supabase = createSupabaseAdmin();
  const { data, error } = await supabase
    .from("weather_assets")
    .select(ASSET_COLUMNS)
    .eq("asset_key", weatherAssetKey())
    .eq("gfs_run", gfsRun)
    .maybeSingle();

  if (error) {
    throw new Error(`Unable to read weather asset ${gfsRun}: ${error.message}`);
  }
  return (data as WeatherAsset | null) ?? null;
}

export async function enqueueAsset(
  gfsRun: string,
  triggerSource: string,
): Promise<"queued" | "already-exists"> {
  const existing = await getAssetForRun(gfsRun);
  if (existing && existing.status !== "failed") {
    return "already-exists";
  }

  const supabase = createSupabaseAdmin();
  if (existing?.status === "failed") {
    const { error } = await supabase
      .from("weather_assets")
      .update({
        status: "queued",
        queued_at: new Date().toISOString(),
        trigger_source: triggerSource,
        error_message: null,
      })
      .eq("id", existing.id)
      .eq("status", "failed");
    if (error) {
      throw new Error(`Unable to requeue weather asset: ${error.message}`);
    }
    return "queued";
  }

  const { error } = await supabase.from("weather_assets").insert({
    asset_key: weatherAssetKey(),
    gfs_run: gfsRun,
    status: "queued",
    trigger_source: triggerSource,
  });

  if (error?.code === "23505") {
    return "already-exists";
  }
  if (error) {
    throw new Error(`Unable to queue weather asset: ${error.message}`);
  }
  return "queued";
}

