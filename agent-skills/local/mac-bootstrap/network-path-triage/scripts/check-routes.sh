#!/bin/sh

set -u

case "$0" in
  */*) script_path=$0 ;;
  *)
    script_path=$(command -v "$0" 2>/dev/null || printf '%s\n' "$0")
    ;;
esac

script_dir=$(CDPATH= cd -- "$(dirname -- "$script_path")" && pwd)
sample_file="$script_dir/../examples/company-hosts.sample.txt"
tun_gateway="198.18.0.1"
hosts_file=""
hosts=""

usage() {
  cat <<'EOF'
Usage:
  check-routes.sh [--tun-gateway <ip>] [--hosts-file <path>] [host1 host2 ...]
  check-routes.sh --sample

Notes:
  - No built-in company host list is treated as canonical.
  - Use --sample only for the bundled example host set.
  - For real incidents, pass the actual hosts from the current environment.
EOF
}

trim_line() {
  printf '%s' "$1" | sed 's/#.*$//; s/^[[:space:]]*//; s/[[:space:]]*$//'
}

append_host() {
  host_value=$1
  if [ -z "$hosts" ]; then
    hosts=$host_value
  else
    hosts=$hosts'
'$host_value
  fi
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --tun-gateway)
      [ "$#" -lt 2 ] && { echo "missing value for --tun-gateway" >&2; exit 1; }
      tun_gateway=$2
      shift 2
      ;;
    --hosts-file)
      [ "$#" -lt 2 ] && { echo "missing value for --hosts-file" >&2; exit 1; }
      hosts_file=$2
      shift 2
      ;;
    --sample)
      hosts_file=$sample_file
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      append_host "$1"
      shift
      ;;
  esac
done

if [ -n "$hosts_file" ]; then
  [ -f "$hosts_file" ] || { echo "hosts file not found: $hosts_file" >&2; exit 1; }
  while IFS= read -r raw_line || [ -n "$raw_line" ]; do
    line=$(trim_line "$raw_line")
    [ -n "$line" ] || continue
    append_host "$line"
  done < "$hosts_file"
fi

[ -n "$hosts" ] || { usage; exit 1; }

printf '%s\n' "$hosts" | while IFS= read -r host; do
  [ -n "$host" ] || continue
  echo "================================================"
  echo "HOST: $host"

  echo "[CNAME]"
  dig +short "$host" CNAME

  echo "[A records]"
  ips=$(dig +short "$host" A | grep -E '^[0-9.]+$' || true)

  if [ -z "$ips" ]; then
    echo "(no A records)"
    continue
  fi

  printf '%s\n' "$ips" | while IFS= read -r ip; do
    [ -n "$ip" ] || continue
    route_info=$(route -n get "$ip" 2>/dev/null || true)
    gateway=$(printf '%s\n' "$route_info" | awk '/gateway:/{print $2; exit}')
    iface=$(printf '%s\n' "$route_info" | awk '/interface:/{print $2; exit}')

    if [ "$gateway" = "$tun_gateway" ]; then
      echo "$ip -> $iface / $gateway [captured by tun gateway; exclude only if the site should keep its original path]"
    else
      echo "$ip -> $iface / $gateway [not captured by tun gateway]"
    fi
  done
done
