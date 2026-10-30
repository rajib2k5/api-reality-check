from typing import overload, Union
import abc
class Base(abc.ABC):
    @abc.abstractmethod
    def run(self) -> int: ...
class Impl(Base):
    def run(self):
        return 1
@overload
def f(x: int) -> int: ...
@overload
def f(x: str) -> str: ...
def f(x: Union[int, str]):
    return x
print(Impl().run(), f(1))
