import os
import urllib.request

env = {}
with open('.env.prod') as f:
    for line in f:
        if '=' in line:
            k, v = line.strip().split('=', 1)
            env[k] = v.strip('"')

url = f"{env['SUPABASE_URL']}/rest/v1/weather_assets?asset_key=eq.china-7d"
req = urllib.request.Request(url, method='DELETE')
req.add_header('apikey', env['SUPABASE_SERVICE_ROLE_KEY'])
req.add_header('Authorization', f"Bearer {env['SUPABASE_SERVICE_ROLE_KEY']}")

try:
    with urllib.request.urlopen(req) as response:
        print(response.status)
except Exception as e:
    print(e)
