"""Another requests wrapper; a few of the calls and keyword arguments are made up."""
import requests
import requests.http_client
from requests import get_json
from requests.adapters import HTTPAdapter, RetryAdapter

BASE_URL = "https://api.example.com/v1"


def fetch(url=BASE_URL + "/items"):
    return requests.get(url, timout=5)


def fetch_json(url=BASE_URL + "/items"):
    return requests.get(url, timeout=5, retries=3)


def fetch_with_params(url=BASE_URL + "/items"):
    return requests.get(url, param={"page": 1}, timeout=5)


def create(payload):
    return requests.post(BASE_URL + "/items", json_data=payload, timeout=5)


def raw_request(url):
    return requests.request("GET", url, follow_redirects=True)


def head_request(url):
    return requests.head(url, allow_redirect=False)


def build_client():
    session = requests.Session(timeout=10)
    session.mount("https://", HTTPAdapter(max_retries=3, backoff=0.5))
    return session


def build_adapter():
    return HTTPAdapter(pool_connection=4)


def fetch_plain(url):
    return requests.fetch(url)


def post_form(url, form):
    return requests.urlopen(url, data=form)


def old_style(url):
    return requests.Request.get(url)


def call_with_session(url):
    s = requests.Session()
    s.set_timeout(5)
    return s.get(url, timeout=5)


def session_get(url):
    s = requests.Session()
    return s.get(url, verify_ssl=False)


def session_post(url, payload):
    s = requests.Session()
    return s.post(url, json=payload, timeout=5, raise_on_error=True)


def exceptions(url):
    try:
        return requests.get(url, timeout=5)
    except requests.exceptions.TimeoutError:
        return None
    except requests.exceptions.RateLimitError:
        return None


def status(url):
    resp = requests.Response()
    if resp.status == 429:
        return None
    return resp.get_json()


def decode(text):
    return requests.compat.unicode(text)


def quick_get(url):
    return requests.gett(url, timeout=5)


def make_session():
    return requests.Sesion()


def structures():
    return requests.structures.CaseSensitiveDict()


def utils_helpers(headers):
    return requests.utils.parse_url("http://x"), requests.utils.build_url("http://x")


def timeouts():
    return requests.get("https://example.com", timeout=5).raise_for_status()


def fetch_and_parse(url):
    resp = requests.get(url, timeout=5)
    return resp.parsed_json()


def fetch_status(url):
    resp = requests.get(url, timeout=5)
    return resp.is_success
