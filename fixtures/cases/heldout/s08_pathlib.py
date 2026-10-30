from pathlib import Path
import tempfile
d = Path(tempfile.mkdtemp())
p = d / "a.txt"
p.write_text("hi", encoding="utf-8")
print(p.read_text(encoding="utf-8"), p.exists(), p.stem, p.suffix, list(d.glob("*.txt")))
p.unlink(missing_ok=True)
d.mkdir(parents=True, exist_ok=True)
