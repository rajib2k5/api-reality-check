"""A project-local package that sits next to the fixture files."""

CONSTANT = 7


def compute(value, scale=2):
    return value * scale * CONSTANT


class Helper:
    def __init__(self, name):
        self.name = name
