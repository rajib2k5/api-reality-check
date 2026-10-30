import re
pat = re.compile(r"(\d+)-(\w+)", flags=re.IGNORECASE)
m = pat.search("12-ab")
print(m.group(1), m.groups(), pat.sub(repl="x", string="1-a 2-b", count=1), re.findall(r"\d", "a1b2"))
print(re.split(r",", "a,b", maxsplit=1), re.fullmatch(r"a+", "aaa"))
