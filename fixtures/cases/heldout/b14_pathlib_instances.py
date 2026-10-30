from pathlib import Path, PurePosixPath
import pathlib
p = Path("/tmp") / "a.txt"
print(p.with_suffix(".csv"), p.parent.name, p.resolve(strict=False), p.is_relative_to("/tmp"), p.parts, p.as_posix(), p.home(), p.expanduser())
pp = PurePosixPath("a/b")
print(pp.match("*/b"), pp.relative_to("a"), pathlib.Path.cwd().anchor, Path.home().drive, p.stat if False else 0)
