import {
  dispatchWeatherGeneration,
  githubDispatchConfigured,
} from "@/lib/github-dispatch";
import { findLatestCompleteGfsRun } from "@/lib/noaa-gfs";
import { enqueueAsset } from "@/lib/weather-assets";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 30;

function authorized(request: Request): boolean {
  const secret = process.env.CRON_SECRET?.trim();
  if (!secret) return false;
  return request.headers.get("authorization") === `Bearer ${secret}`;
}

export async function GET(request: Request): Promise<Response> {
  if (!authorized(request)) {
    return Response.json(
      { error: "unauthorized" },
      { status: 401, headers: { "Cache-Control": "no-store" } },
    );
  }

  try {
    const gfsRun = await findLatestCompleteGfsRun();
    if (!gfsRun) {
      return Response.json(
        { status: "no_complete_gfs_run" },
        { status: 503, headers: { "Cache-Control": "no-store" } },
      );
    }

    const queueResult = await enqueueAsset(gfsRun, "vercel-cron");
    if (queueResult === "already-exists") {
      return Response.json(
        { status: "skipped", reason: "gfs_run_already_registered", gfsRun },
        { headers: { "Cache-Control": "no-store" } },
      );
    }

    if (!githubDispatchConfigured()) {
      return Response.json(
        {
          status: "queued",
          gfsRun,
          dispatched: false,
          message:
            "GitHub dispatch is not configured. The scheduled GitHub workflow can claim this run.",
        },
        { status: 202, headers: { "Cache-Control": "no-store" } },
      );
    }

    await dispatchWeatherGeneration(gfsRun);
    return Response.json(
      { status: "queued", gfsRun, dispatched: true },
      { status: 202, headers: { "Cache-Control": "no-store" } },
    );
  } catch (error) {
    return Response.json(
      { status: "error", detail: String(error) },
      { status: 500, headers: { "Cache-Control": "no-store" } },
    );
  }
}

