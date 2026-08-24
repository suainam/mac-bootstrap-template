# Geo & Weather Zero-Auth APIs

## 1. Open-Meteo Weather API
- **Endpoint**: `https://api.open-meteo.com/v1/forecast`
- **Auth**: None
- **Rate Limit**: 10,000 calls/day (Free non-commercial)
- **Usage**:
  ```bash
  # Current weather and hourly forecast for Beijing (39.9042, 116.4074)
  curl -s "https://api.open-meteo.com/v1/forecast?latitude=39.9042&longitude=116.4074&current_weather=true&hourly=temperature_2m,relativehumidity_2m,precipitation"
  ```
- **Key Fields**:
  - `current_weather.temperature`: Current temperature in °C
  - `current_weather.windspeed`: Windspeed in km/h
  - `current_weather.weathercode`: WMO weather interpretation code

---

## 2. REST Countries
- **Endpoint**: `https://restcountries.com/v3.1/`
- **Auth**: None
- **Usage**:
  ```bash
  # Query country by name
  curl -s "https://restcountries.com/v3.1/name/japan"
  # Query country by ISO code
  curl -s "https://restcountries.com/v3.1/alpha/cn"
  ```
- **Key Fields**:
  - `name.common`, `capital`, `region`, `population`, `currencies`, `languages`

---

## 3. OpenStreetMap Nominatim (Geocoding)
- **Endpoint**: `https://nominatim.openstreetmap.org/search`
- **Auth**: None (Must include meaningful `User-Agent`)
- **Usage**:
  ```bash
  curl -s -H "User-Agent: mac-bootstrap-agent/1.0" \
    "https://nominatim.openstreetmap.org/search?q=Tokyo+Tower&format=json&limit=1"
  ```
- **Key Fields**:
  - `lat`: Latitude
  - `lon`: Longitude
  - `display_name`: Formatted address
