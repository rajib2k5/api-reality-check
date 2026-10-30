import numpy as np
class Cfg:
    dtype = np.float64
    scale = 2.0
    def run(self):
        return np.zeros(3, dtype=self.dtype) * self.scale
c = Cfg()
print(c.run(), Cfg.dtype, c.scale)
