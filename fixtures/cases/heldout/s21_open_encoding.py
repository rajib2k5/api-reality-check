import tempfile, os
fd, path = tempfile.mkstemp(suffix=".txt")
os.close(fd)
with open(path, "w", encoding="utf-8", newline="") as fh:
    fh.write("x")
with open(path, mode="r", encoding="utf-8", errors="replace") as fh:
    print(fh.read())
os.remove(path)
