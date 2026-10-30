from dataclasses import dataclass, field, asdict, replace
import dataclasses
@dataclass(frozen=True, order=True)
class P:
    x: int
    y: list = field(default_factory=list, repr=False)
p = P(x=1)
q = replace(p, x=2)
print(asdict(q), dataclasses.fields(P)[0].name, dataclasses.is_dataclass(p), p.x, q.y)
