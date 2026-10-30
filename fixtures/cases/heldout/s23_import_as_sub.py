import os.path as osp
import xml.etree.ElementTree as ET
import urllib.parse as up
print(osp.join("a", "b"), ET.fromstring("<a/>").tag, up.urlencode({"a": 1}, doseq=True), up.quote("a b", safe=""))
