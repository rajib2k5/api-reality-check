from typing import Optional, Dict, List, TypedDict, Protocol, cast, TYPE_CHECKING
import typing as t
class TD(TypedDict, total=False):
    a: int
def f(x: Optional[int] = None) -> Dict[str, List[int]]:
    return {"a": [x or 0]}
print(f(x=1), cast(int, "x"), t.get_type_hints(f), t.NamedTuple("NT", [("a", int)])(a=1))
