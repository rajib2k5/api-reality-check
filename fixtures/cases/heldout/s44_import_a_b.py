import os.path
import xml.etree.ElementTree
import concurrent.futures
import importlib.metadata
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
    fut = ex.submit(sum, [1, 2])
print(os.path.exists("/"), xml.etree.ElementTree.Element("a").tag, fut.result(timeout=1), importlib.metadata.version("numpy"))
