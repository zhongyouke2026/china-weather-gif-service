import { createSupabaseAdmin } from "@/lib/supabase-admin";
import { getLatestReadyAsset, type WeatherAsset } from "@/lib/weather-assets";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const revalidate = 0;
export const maxDuration = 30;

const CACHE_CONTROL =
  "public, max-age=300, s-maxage=900, stale-while-revalidate=60, must-revalidate";

function etagFor(asset: WeatherAsset): string {
  return `"${asset.sha256 || asset.gfs_run}"`;
}

function headersFor(asset: WeatherAsset): Headers {
  const generatedAt = asset.generated_at || asset.finished_at || asset.updated_at;
  return new Headers({
    "Cache-Control": CACHE_CONTROL,
    "CDN-Cache-Control": "public, s-maxage=900, stale-while-revalidate=60",
    "Vercel-CDN-Cache-Control":
      "public, s-maxage=900, stale-while-revalidate=60",
    "Content-Type": asset.content_type || "image/gif",
    "Content-Disposition": `inline; filename="china-weather-${asset.gfs_run}.gif"`,
    ETag: etagFor(asset),
    "Last-Modified": new Date(generatedAt).toUTCString(),
    "X-Weather-GFS-Run": asset.gfs_run,
    "X-Content-Type-Options": "nosniff",
  });
}

function isNotModified(request: Request, asset: WeatherAsset): boolean {
  const ifNoneMatch = request.headers.get("if-none-match");
  if (ifNoneMatch && ifNoneMatch.split(",").map((value) => value.trim()).includes(etagFor(asset))) {
    return true;
  }

  const ifModifiedSince = request.headers.get("if-modified-since");
  if (!ifModifiedSince) return false;
  const generatedAt = asset.generated_at || asset.finished_at || asset.updated_at;
  const requestTime = Date.parse(ifModifiedSince);
  const assetTime = Date.parse(generatedAt);
  return Number.isFinite(requestTime) && requestTime >= Math.floor(assetTime / 1000) * 1000;
}

async function handle(request: Request, includeBody: boolean): Promise<Response> {
  let asset: WeatherAsset | null;
  try {
    asset = await getLatestReadyAsset();
  } catch (error) {
    return Response.json(
      { error: "weather_asset_lookup_failed", detail: String(error) },
      { status: 503, headers: { "Cache-Control": "no-store" } },
    );
  }

  if (!asset?.storage_bucket || !asset.storage_path) {
    return Response.json(
      {
        error: "weather_asset_not_ready",
        message: "Run the batch generator once, then retry this URL.",
      },
      { status: 404, headers: { "Cache-Control": "no-store" } },
    );
  }

  const headers = headersFor(asset);
  if (isNotModified(request, asset)) {
    return new Response(null, { status: 304, headers });
  }
  if (!includeBody) {
    if (asset.byte_size != null) {
      headers.set("Content-Length", String(asset.byte_size));
    }
    return new Response(null, { status: 200, headers });
  }

  const supabase = createSupabaseAdmin();
  const { data, error } = await supabase.storage
    .from(asset.storage_bucket)
    .download(asset.storage_path);
  if (error || !data) {
    return Response.json(
      { error: "weather_asset_download_failed", detail: error?.message },
      { status: 502, headers: { "Cache-Control": "no-store" } },
    );
  }

  const body = await data.arrayBuffer();
  headers.set("Content-Length", String(body.byteLength));
  return new Response(body, { status: 200, headers });
}

export async function GET(request: Request): Promise<Response> {
  return handle(request, true);
}

export async function HEAD(request: Request): Promise<Response> {
  return handle(request, false);
}

