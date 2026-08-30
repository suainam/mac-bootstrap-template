# Knowledge, Encyclopedia & Documentation Zero-Auth APIs

## 1. Wikipedia REST API
- **Endpoint**: `https://en.wikipedia.org/api/rest_v1/page/summary/{title}`
- **Auth**: None (Must include meaningful `User-Agent`)
- **Usage**:
  ```bash
  # English Wikipedia summary
  curl -s -H "User-Agent: mac-bootstrap-agent/1.0" \
    "https://en.wikipedia.org/api/rest_v1/page/summary/Artificial_intelligence"
  # Chinese Wikipedia summary
  curl -s -H "User-Agent: mac-bootstrap-agent/1.0" \
    "https://zh.wikipedia.org/api/rest_v1/page/summary/%E4%BA%BA%E5%B7%A5%E6%99%BA%E8%83%BD"
  ```
- **Key Fields**:
  - `title`: Canonical page title
  - `extract`: Clean plain-text lead summary
  - `description`: One-line concept summary

---

## 2. Open Library Books API
- **Endpoint**: `https://openlibrary.org/api/books`
- **Auth**: None
- **Usage**:
  ```bash
  # Query book by ISBN
  curl -s "https://openlibrary.org/api/books?bibkeys=ISBN:9780131103627&format=json&jscmd=data"
  ```
- **Key Fields**:
  - `title`, `authors[].name`, `number_of_pages`, `publish_date`
