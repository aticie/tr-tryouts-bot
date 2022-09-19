from enum import Enum


class Lobby(Enum):
    LOBBY_STARTED = 0
    LOBBY_WAITING = 1
    LOBBY_PLAYING = 2
    LOBBY_ENDING = 3
