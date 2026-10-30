import numpy as np
class Model:
    def __init__(self, n):
        self.n = n
        self.w = np.zeros(n)
    def fit(self, x):
        self.w = self.w + x
        return self
    @property
    def norm(self):
        return np.linalg.norm(self.w)
    @classmethod
    def build(cls, n=3):
        return cls(n)
m = Model.build(n=2).fit(np.ones(2))
print(m.norm, m.w.sum(), Model(3).n)
