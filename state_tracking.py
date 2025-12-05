from enum import Enum


class Head(Enum):
    root = 0
    quiz = 1
    options = 2
    option = 3


class BuildingStateTracker:
    def __init__(self):
        self.__level = 0
        self.__empty = True
        self.built = False

    @property
    def level(self):
        return self.__level

    @property
    def empty(self):
        return self.__empty

    @property
    def head(self) -> Head:
        return Head(self.__level)

    def increase_level(self):
        self.__empty = False
        self.__level += 1

    def decrease_level(self):
        if self.__level == 0:
            raise RuntimeError("already on level 0")
        self.__level -= 1

    @property
    def valid(self):
        return self.__level == 0 and not self.__empty
