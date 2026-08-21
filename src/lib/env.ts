export function requiredEnv(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) {
    throw new Error(`Missing required environment variable: ${name}`);
  }
  return value;
}

export function optionalEnv(name: string, fallback: string): string {
  return process.env[name]?.trim() || fallback;
}

export function weatherAssetKey(): string {
  return optionalEnv("WEATHER_ASSET_KEY", "china-7d");
}

export function weatherStorageBucket(): string {
  return optionalEnv("WEATHER_STORAGE_BUCKET", "weather-assets");
}

