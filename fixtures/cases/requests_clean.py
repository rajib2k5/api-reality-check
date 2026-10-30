"""HTTP client helpers around the requests library."""
import json

import requests
from requests.adapters import HTTPAdapter
from requests.auth import HTTPBasicAuth
from requests.exceptions import ConnectionError, HTTPError, RequestException, Timeout
from urllib3.util.retry import Retry

BASE_URL = "https://api.example.com/v1"


def build_session(token="demo-token", retries=3):
    session = requests.Session()
    session.headers.update({"Accept": "application/json", "User-Agent": "demo-client/1.0"})
    session.headers["Authorization"] = f"Bearer {token}"
    session.params = {"format": "json"}
    session.verify = True
    retry = Retry(total=retries, backoff_factor=0.5, status_forcelist=[429, 500, 502, 503])
    adapter = HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=8)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def fetch_items(url=BASE_URL + "/items", page=1):
    resp = requests.get(url, params={"page": page, "per_page": 50}, timeout=(3.05, 10), allow_redirects=True)
    resp.raise_for_status()
    data = resp.json()
    return data["items"], resp.status_code, resp.headers.get("Content-Type"), resp.elapsed


def create_item(name="widget"):
    resp = requests.post(
        BASE_URL + "/items",
        json={"name": name},
        headers={"Content-Type": "application/json"},
        timeout=10,
    )
    return resp.ok, resp.text, resp.reason, resp.url


def login(user="demo", password="secret"):
    resp = requests.get(BASE_URL + "/me", auth=HTTPBasicAuth(user, password), timeout=5)
    return resp.status_code == requests.codes.ok


def safe_fetch(url=BASE_URL + "/items"):
    try:
        resp = requests.get(url, timeout=5)
        resp.raise_for_status()
        return resp.json()
    except Timeout:
        return {"error": "timeout"}
    except HTTPError as exc:
        return {"error": exc.response.status_code}
    except ConnectionError:
        return {"error": "connection"}
    except RequestException as exc:
        return {"error": str(exc)}


def stream_download(url=BASE_URL + "/export", dest="export.bin"):
    with requests.get(url, stream=True, timeout=30) as resp:
        resp.raise_for_status()
        total = 0
        with open(dest, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=8192):
                fh.write(chunk)
                total += len(chunk)
    return total


def paginate(session=None, url=BASE_URL + "/items"):
    session = session or build_session()
    results = []
    while url:
        resp = session.get(url, timeout=10)
        resp.raise_for_status()
        payload = resp.json()
        results.extend(payload["items"])
        url = payload.get("next")
    return results


def update_and_delete(session=None):
    session = session or build_session()
    put = session.put(BASE_URL + "/items/1", data=json.dumps({"name": "x"}), timeout=10)
    patch = session.patch(BASE_URL + "/items/1", json={"name": "y"}, timeout=10)
    gone = session.delete(BASE_URL + "/items/1", timeout=10)
    head = session.head(BASE_URL + "/items", timeout=10)
    opts = session.options(BASE_URL + "/items", timeout=10)
    return put.status_code, patch.status_code, gone.status_code, head.headers, opts.ok


def prepared_request():
    req = requests.Request("GET", BASE_URL + "/items", params={"q": "a b"}, headers={"X-Trace": "1"})
    prepared = req.prepare()
    with requests.Session() as session:
        resp = session.send(prepared, timeout=5, allow_redirects=False)
    return prepared.url, resp.history, resp.cookies, resp.encoding


def inspect_response():
    resp = requests.request("GET", BASE_URL + "/items", timeout=5)
    return resp.content, resp.links, resp.is_redirect, resp.apparent_encoding, list(resp.iter_lines())


def helpers():
    from requests.utils import quote, requote_uri

    return quote("a b/c", safe=""), requote_uri(BASE_URL + "/a b"), requests.__version__


def run():
    session = build_session(token="abc")
    return fetch_items(), create_item(), login(), safe_fetch(), paginate(session)
