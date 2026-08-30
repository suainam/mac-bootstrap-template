---
name: public-api-index
description: Query zero-auth public REST APIs (weather, geo/IP, crypto/forex, network/DNS, encyclopedia) via direct curl or reusable query scripts.
---

# Public API Direct Index

Direct, zero-authentication public REST endpoints for instant agent data retrieval without API keys.

## Quick Router

| Domain | Primary Sources | Reference Spec |
| :--- | :--- | :--- |
| **Geo & Weather** | Open-Meteo, REST Countries, Nominatim Geocoding | `references/geo-weather.md` |
| **Network & Infra** | IP-API, Cloudflare 1.1.1.1 DoH, crt.sh Certs | `references/dev-infra.md` |
| **Crypto & Forex** | CoinGecko Simple, ExchangeRate-API Open | `references/finance-crypto.md` |
| **Knowledge & Docs** | Wikipedia REST, Open Library Books | `references/knowledge-data.md` |

## Reusable Query Tool

Use the included helper script for formatted queries with built-in timeouts and JSON extraction:

```bash
# General query with dot-path extraction
python3 template/agent-skills/local/global/public-api-index/scripts/query_api.py ip 1.1.1.1
python3 template/agent-skills/local/global/public-api-index/scripts/query_api.py weather 39.9042 116.4074
python3 template/agent-skills/local/global/public-api-index/scripts/query_api.py crypto bitcoin,ethereum
python3 template/agent-skills/local/global/public-api-index/scripts/query_api.py forex USD
python3 template/agent-skills/local/global/public-api-index/scripts/query_api.py dns example.com A
```

## Direct Curl Patterns

```bash
# Weather (Open-Meteo)
curl -s "https://api.open-meteo.com/v1/forecast?latitude=39.9042&longitude=116.4074&current_weather=true"

# IP Geo-lookup (ip-api)
curl -s "http://ip-api.com/json/1.1.1.1"

# Forex Rates (ExchangeRate-API)
curl -s "https://open.er-api.com/v6/latest/USD"

# Crypto Price (CoinGecko)
curl -s "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum&vs_currencies=usd"

# DNS over HTTPS (Cloudflare 1.1.1.1)
curl -s -H "accept: application/dns-json" "https://cloudflare-dns.com/dns-query?name=example.com&type=A"
```
