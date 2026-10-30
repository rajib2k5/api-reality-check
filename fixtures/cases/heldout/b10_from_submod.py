from os import path, sep
from concurrent import futures
from xml.etree import ElementTree as ET
from numpy import random as npr, linalg
from pandas import api
from requests import exceptions, adapters
print(path.join("a"), sep, futures.ThreadPoolExecutor, ET.Element("x"), npr.default_rng(1).random(), linalg.det([[1, 0], [0, 1]]), api.types.is_bool_dtype, exceptions.HTTPError, adapters.HTTPAdapter)
