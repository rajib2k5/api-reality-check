import re
if (m := re.match(r"(\d+)", "12a")) is not None:
    print(m.group(0), m.end())
data = [1, 2, 3]
if (n := len(data)) > 2:
    print(n)
