from dataclasses import dataclass
from enum import Enum


class LobbyState(Enum):
    LOBBY_STARTED = 0
    LOBBY_INITIALIZED = 1
    LOBBY_WAITING = 2
    LOBBY_DISCONNECTED = 3
    LOBBY_PLAYING = 4
    LOBBY_ENDING = 5


@dataclass
class LobbyDetails:
    """Class for keeping track of the played lobby."""
    lobby_channel: str
    lobby_url: str
    player: str
    map_idx: int = 0
    lobby_state: LobbyState = LobbyState.LOBBY_STARTED
    player_leave_count: int = 0
