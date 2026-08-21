import { createClient } from "@supabase/supabase-js";

import { requiredEnv } from "@/lib/env";

export function createSupabaseAdmin() {
  return createClient(
    requiredEnv("SUPABASE_URL"),
    requiredEnv("SUPABASE_SERVICE_ROLE_KEY"),
    {
      auth: {
        autoRefreshToken: false,
        persistSession: false,
      },
    },
  );
}

