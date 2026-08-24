# Developer & Network Infrastructure Zero-Auth APIs

## 1. IP-API (Geolocation & ASN)
- **Endpoint**: `http://ip-api.com/json/{ip_or_domain}`
- **Auth**: None
- **Rate Limit**: 45 requests/minute from same IP
- **Usage**:
  ```bash
  curl -s "http://ip-api.com/json/8.8.8.8?fields=status,message,country,regionName,city,zip,lat,lon,timezone,isp,org,as,query"
  ```
- **Key Fields**:
  - `country`, `city`, `isp`, `as`, `query`

---

## 2. Cloudflare 1.1.1.1 DNS over HTTPS (DoH)
- **Endpoint**: `https://cloudflare-dns.com/dns-query`
- **Auth**: None
- **Usage**:
  ```bash
  # Query A records
  curl -s -H "accept: application/dns-json" "https://cloudflare-dns.com/dns-query?name=github.com&type=A"
  # Query TXT records
  curl -s -H "accept: application/dns-json" "https://cloudflare-dns.com/dns-query?name=github.com&type=TXT"
  ```
- **Key Fields**:
  - `Answer[].data`: IP address or record content
  - `Status`: 0 = NOERROR

---

## 3. crt.sh (Certificate Transparency Log Search)
- **Endpoint**: `https://crt.sh/`
- **Auth**: None
- **Usage**:
  ```bash
  # Find subdomains for a domain
  curl -s "https://crt.sh/?q=%.example.com&output=json"
  ```
- **Key Fields**:
  - `name_value`: Registered subdomain names
  - `issuer_name`: Certificate Authority
