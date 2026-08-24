# Finance & Cryptocurrency Zero-Auth APIs

## 1. CoinGecko Simple Price API
- **Endpoint**: `https://api.coingecko.com/api/v3/simple/price`
- **Auth**: None
- **Rate Limit**: 10-30 requests/minute (Public Demo)
- **Usage**:
  ```bash
  # Price and 24h change for Bitcoin & Ethereum
  curl -s "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum,solana&vs_currencies=usd,cny&include_24hr_change=true"
  ```
- **Key Fields**:
  - `<coin>.<currency>`: Current spot price
  - `<coin>.<currency>_24h_change`: 24h percentage delta

---

## 2. Open Exchange Rates (er-api.com)
- **Endpoint**: `https://open.er-api.com/v6/latest/{BASE}`
- **Auth**: None
- **Rate Limit**: Real-time hourly cached
- **Usage**:
  ```bash
  # Fetch USD-based forex rates
  curl -s "https://open.er-api.com/v6/latest/USD"
  ```
- **Key Fields**:
  - `rates.CNY`, `rates.EUR`, `rates.JPY`, `rates.GBP`
  - `time_last_update_utc`: Timestamp of rate snapshot
