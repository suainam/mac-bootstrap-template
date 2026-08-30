#!/usr/bin/env python3
"""Reusable zero-auth public API query runner.

Handles network timeouts, JSON validation, and clean formatting.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any
import urllib.parse
import urllib.request


def fetch_json(url: str, headers: dict[str, str] | None = None, timeout: int = 10) -> Any:
    req_headers = {"User-Agent": "mac-bootstrap-agent/1.0", **(headers or {})}
    req = urllib.request.Request(url, headers=req_headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
            return json.loads(data.decode("utf-8"))
    except Exception as e:
        sys.stderr.write(f"Error fetching {url}: {e}\n")
        sys.exit(1)


def cmd_ip(args: argparse.Namespace) -> None:
    target = args.target.strip()
    url = f"http://ip-api.com/json/{target}?fields=status,message,country,regionName,city,zip,lat,lon,timezone,isp,org,as,query"
    data = fetch_json(url)
    print(json.dumps(data, indent=2, ensure_ascii=False))


def cmd_weather(args: argparse.Namespace) -> None:
    lat = args.lat
    lon = args.lon
    url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true&hourly=temperature_2m,relativehumidity_2m,precipitation"
    data = fetch_json(url)
    print(json.dumps(data, indent=2, ensure_ascii=False))


def cmd_crypto(args: argparse.Namespace) -> None:
    coins = args.coins
    vs = args.vs
    url = f"https://api.coingecko.com/api/v3/simple/price?ids={coins}&vs_currencies={vs}&include_24hr_change=true"
    data = fetch_json(url)
    print(json.dumps(data, indent=2, ensure_ascii=False))


def cmd_forex(args: argparse.Namespace) -> None:
    base = args.base.upper()
    url = f"https://open.er-api.com/v6/latest/{base}"
    data = fetch_json(url)
    print(json.dumps(data, indent=2, ensure_ascii=False))


def cmd_dns(args: argparse.Namespace) -> None:
    domain = args.domain
    rtype = args.type.upper()
    url = f"https://cloudflare-dns.com/dns-query?name={urllib.parse.quote(domain)}&type={rtype}"
    data = fetch_json(url, headers={"Accept": "application/dns-json"})
    print(json.dumps(data, indent=2, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description="Query zero-auth public REST APIs")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # IP
    p_ip = subparsers.add_parser("ip", help="Query IP geolocation")
    p_ip.add_argument("target", help="IP address or domain (or '' for self)")
    p_ip.set_defaults(func=cmd_ip)

    # Weather
    p_weather = subparsers.add_parser("weather", help="Query Open-Meteo weather")
    p_weather.add_argument("lat", type=float, help="Latitude")
    p_weather.add_argument("lon", type=float, help="Longitude")
    p_weather.set_defaults(func=cmd_weather)

    # Crypto
    p_crypto = subparsers.add_parser("crypto", help="Query CoinGecko crypto prices")
    p_crypto.add_argument("coins", help="Comma-separated coin ids (e.g. bitcoin,ethereum)")
    p_crypto.add_argument("--vs", default="usd", help="Target currency (default: usd)")
    p_crypto.set_defaults(func=cmd_crypto)

    # Forex
    p_forex = subparsers.add_parser("forex", help="Query Open Exchange Rates")
    p_forex.add_argument("base", default="USD", nargs="?", help="Base currency (default: USD)")
    p_forex.set_defaults(func=cmd_forex)

    # DNS
    p_dns = subparsers.add_parser("dns", help="Query DNS records via Cloudflare DoH")
    p_dns.add_argument("domain", help="Domain name")
    p_dns.add_argument("type", default="A", nargs="?", help="Record type (A, AAAA, TXT, MX, CNAME)")
    p_dns.set_defaults(func=cmd_dns)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
