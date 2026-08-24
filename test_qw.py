import os
import urllib.request
import json

env = {}
with open('.env.prod') as f:
    for line in f:
        if '=' in line:
            k, v = line.strip().split('=', 1)
            env[k] = v.strip('"')

req = urllib.request.Request(f"https://api.qweather.com/v7/tropical/storm-list?basin=NP&year=2026&key={env['QWEATHER_API_KEY']}")
with urllib.request.urlopen(req) as response:
    print(response.read().decode())
