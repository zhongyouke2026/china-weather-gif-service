import { requiredEnv } from "@/lib/env";

export function githubDispatchConfigured(): boolean {
  return Boolean(
    process.env.GITHUB_ACTIONS_REPOSITORY?.trim() &&
      process.env.GITHUB_ACTIONS_TOKEN?.trim(),
  );
}

export async function dispatchWeatherGeneration(gfsRun: string): Promise<void> {
  const repository = requiredEnv("GITHUB_ACTIONS_REPOSITORY");
  const token = requiredEnv("GITHUB_ACTIONS_TOKEN");
  if (!/^[^/]+\/[^/]+$/.test(repository)) {
    throw new Error("GITHUB_ACTIONS_REPOSITORY must use owner/repository format");
  }

  const response = await fetch(
    `https://api.github.com/repos/${repository}/dispatches`,
    {
      method: "POST",
      headers: {
        Accept: "application/vnd.github+json",
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
        "X-GitHub-Api-Version": "2022-11-28",
      },
      body: JSON.stringify({
        event_type: "weather-gfs-ready",
        client_payload: { gfs_run: gfsRun },
      }),
    },
  );

  if (!response.ok) {
    const body = await response.text();
    throw new Error(
      `GitHub dispatch failed (${response.status}): ${body.slice(0, 500)}`,
    );
  }
}

