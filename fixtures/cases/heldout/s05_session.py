import requests
s = requests.Session()
s.headers.update({"User-Agent": "x"})
s.mount("https://", requests.adapters.HTTPAdapter(max_retries=3, pool_connections=5))
r = s.get("https://example.com", params={"q": 1}, timeout=5, allow_redirects=True)
r2 = s.post("https://example.com", json={"a": 1}, timeout=(3, 5), verify=True)
r.raise_for_status()
print(r.status_code, r.json(), r2.text)
s.close()
