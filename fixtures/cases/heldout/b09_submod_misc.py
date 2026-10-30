import xml.dom.minidom
import email.mime.text
import logging.handlers
import http.client
import unittest.mock
import importlib.util
import json.decoder
import urllib.request
print(xml.dom.minidom.parseString("<a/>").documentElement.tagName, email.mime.text.MIMEText("x").as_string()[:5])
print(logging.handlers.RotatingFileHandler, http.client.HTTPSConnection, unittest.mock.MagicMock(spec=list), importlib.util.find_spec("json"))
print(json.decoder.JSONDecodeError, urllib.request.Request("http://x", method="GET").get_method())
