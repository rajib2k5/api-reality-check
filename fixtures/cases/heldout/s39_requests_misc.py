import requests
from requests.adapters import HTTPAdapter
from requests.exceptions import HTTPError, Timeout, ConnectionError
from urllib3.util.retry import Retry
retry = Retry(total=3, backoff_factor=0.5, status_forcelist=[500, 502], allowed_methods=["GET"])
s = requests.Session()
s.mount("https://", HTTPAdapter(max_retries=retry))
try:
    r = requests.get("https://example.com", headers={"A": "b"}, timeout=5, stream=True)
    for chunk in r.iter_content(chunk_size=1024):
        pass
except (HTTPError, Timeout, ConnectionError) as e:
    print(e)
print(requests.codes.ok, requests.Request("GET", "https://x").prepare().url)
