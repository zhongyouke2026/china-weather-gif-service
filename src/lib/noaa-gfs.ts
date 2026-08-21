import { optionalEnv } from "@/lib/env";

const GFS_CYCLES = [0, 6, 12, 18] as const;
const SEARCH_CYCLES = 16;

function formatRun(date: Date): string {
  const year = date.getUTCFullYear().toString().padStart(4, "0");
  const month = (date.getUTCMonth() + 1).toString().padStart(2, "0");
  const day = date.getUTCDate().toString().padStart(2, "0");
  const hour = date.getUTCHours().toString().padStart(2, "0");
  return `${year}${month}${day}${hour}`;
}

export function candidateGfsRuns(now = new Date()): string[] {
  const hour = now.getUTCHours();
  const cycle = [...GFS_CYCLES].reverse().find((value) => value <= hour) ?? 18;
  const first = new Date(now);
  first.setUTCMinutes(0, 0, 0);
  first.setUTCHours(cycle);
  if (cycle === 18 && hour < 18) {
    first.setUTCDate(first.getUTCDate() - 1);
  }

  return Array.from({ length: SEARCH_CYCLES }, (_, index) => {
    const candidate = new Date(first);
    candidate.setUTCHours(candidate.getUTCHours() - index * 6);
    return formatRun(candidate);
  });
}

export function gfsIndexUrl(gfsRun: string, forecastHour = 168): string {
  const date = gfsRun.slice(0, 8);
  const cycle = gfsRun.slice(8, 10);
  const base = optionalEnv(
    "NOAA_GFS_BASE_URL",
    "https://nomads.ncep.noaa.gov",
  ).replace(/\/$/, "");
  const hour = forecastHour.toString().padStart(3, "0");
  return `${base}/pub/data/nccf/com/gfs/prod/gfs.${date}/${cycle}/atmos/gfs.t${cycle}z.pgrb2.0p25.f${hour}.idx`;
}

async function isAvailable(url: string): Promise<boolean> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 8_000);
  try {
    const response = await fetch(url, {
      method: "GET",
      headers: { Range: "bytes=0-0" },
      cache: "no-store",
      signal: controller.signal,
    });
    return response.ok;
  } catch {
    return false;
  } finally {
    clearTimeout(timeout);
  }
}

export async function findLatestCompleteGfsRun(): Promise<string | null> {
  for (const run of candidateGfsRuns()) {
    if (await isAvailable(gfsIndexUrl(run, 168))) {
      return run;
    }
  }
  return null;
}

