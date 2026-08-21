import { getLatestReadyAsset } from "@/lib/weather-assets";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: Request): Promise<Response> {
  try {
    const asset = await getLatestReadyAsset();
    if (!asset) {
      return Response.json(
        { status: "not_ready" },
        { status: 404, headers: { "Cache-Control": "no-store" } },
      );
    }

    const publicGifUrl = new URL("/weather/china.gif", request.url).toString();
    return Response.json(
      {
        status: asset.status,
        assetKey: asset.asset_key,
        gfsRun: asset.gfs_run,
        generatedAt: asset.generated_at,
        forecastStart: asset.forecast_start,
        forecastEnd: asset.forecast_end,
        frameCount: asset.frame_count,
        byteSize: asset.byte_size,
        sha256: asset.sha256,
        gifUrl: publicGifUrl,
        metadata: asset.metadata,
      },
      {
        headers: {
          "Cache-Control":
            "public, max-age=60, s-maxage=300, stale-while-revalidate=60",
        },
      },
    );
  } catch (error) {
    return Response.json(
      { status: "error", detail: String(error) },
      { status: 503, headers: { "Cache-Control": "no-store" } },
    );
  }
}

