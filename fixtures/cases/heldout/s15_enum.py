import enum
from enum import Enum, auto, IntEnum
class Color(Enum):
    RED = auto()
    GREEN = auto()
class N(IntEnum):
    ONE = 1
print(Color.RED.name, Color.RED.value, Color["GREEN"], N.ONE + 1, list(Color), enum.unique(Color))
