import itertools as it
from itertools import chain, groupby, islice, product, accumulate
print(list(chain.from_iterable([[1], [2]])), list(islice(it.count(start=1, step=2), 3)))
print(list(product([1, 2], repeat=2)), list(accumulate([1, 2, 3], initial=0)), [k for k, _ in groupby("aab", key=str.upper)])
print(list(it.zip_longest([1], [2, 3], fillvalue=0)), list(it.pairwise([1, 2, 3])), list(it.combinations(range(3), r=2)))
