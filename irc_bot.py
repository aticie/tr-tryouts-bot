from __future__ import annotations

import datetime
import json
import logging
from typing import List, Callable, Any, Dict

import irc
import irc.bot
import irc.client

from beatmap import Beatmap
from lobbies import LobbyState, LobbyDetails
from sheets import TryoutLobbiesSheet, PlayersSheet

logger = logging.getLogger("tryouts-bot")


# noinspection PyTypeChecker
class TryoutsBot(irc.bot.SingleServerIRCBot):
    MAX_ALLOWED_LEAVES = 1
    BEFORE_READY_WAIT_SECONDS = 120
    DISCONNECT_WAIT_TIMEOUT = 300
    MAX_ALLOWED_PLAYS = 1

    def __init__(
        self,
        nickname: str,
        password: str,
        mappool: List[Beatmap],
        allowed_players: List[str] = None,
    ):
        logger.debug(f"TryoutsBot initating: {nickname} {password} {mappool}")
        irc.bot.SingleServerIRCBot.__init__(
            self, [("irc.ppy.sh", 6667, password)], nickname, nickname
        )
        with open("settings.json", encoding="utf-8") as f:
            self.settings = json.load(f)

        self.recon = irc.bot.ExponentialBackoff(min_interval=5, max_interval=30)

        self.tournament_start = datetime.datetime.fromisoformat(
            self.settings["tournamentStart"]
        )
        self.tournament_end = datetime.datetime.fromisoformat(
            self.settings["tournamentEnd"]
        )

        self.ignored_events = ["all_raw_messages", "quit"]

        self.mappool = mappool
        if allowed_players is None:
            self.allowed_players = []
        else:
            self.allowed_players = allowed_players

        self.last_lobby_requester = ""

        self.tournament_name = self.settings["tournamentName"]

        self.active_lobbies: Dict[str, LobbyDetails] = {}
        self.played_lobbies: Dict[str, List[LobbyDetails]] = {}
        self.connection.set_rate_limit(1)

    def _on_kick(
        self, connection: irc.client.ServerConnection, event: irc.client.Event
    ):
        channel = event.target

        player_to_be_removed = None
        for player, lobby_details in self.active_lobbies.items():
            if lobby_details.lobby_channel == channel:
                player_to_be_removed = player

        if player_to_be_removed:
            logger.debug(
                f"Removing {player_to_be_removed} from active lobbies because we are kicked?"
            )
            self.active_lobbies.pop(player_to_be_removed)
        else:
            logger.debug(
                f"We are kicked but I couldn't find the active lobby. The lobbies were: {self.active_lobbies}"
            )

    def on_privmsg(
        self, connection: irc.client.ServerConnection, event: irc.client.Event
    ):
        """Receive a privmsg event

        Handles a privmsg event. Calls the corresponding function depending on the message.
        If the message is:
        - !q: Handle queue command. Start a private lobby for the player.
        """
        author = event.source.nick
        message = event.arguments[0]

        if author == "BanchoBot":
            if message.startswith("Created the tournament"):
                self.parse_and_start_lobby(message=message)
            elif message.startswith("You cannot create any more tournament matches."):
                self.send(self.last_lobby_requester, self.settings["lobbyFull"])
            elif message.startswith("Stats for"):
                self.add_player_to_sheet(message=message)
        else:
            if message == "!play":
                self.make_lobby(author=author)
            elif message == "!invite":
                self.invite_lobby(author=author)

    def on_pubmsg(
        self, connection: irc.client.ServerConnection, event: irc.client.Event
    ):
        """Receive a pubmsg event

        Handles a pubmsg event. Calls the corresponding function depending on the message.
        If the message is from BanchoBot:
        - Start the lobby if timer ends or player readies up
        """
        author = event.source.nick
        channel = event.target
        message = event.arguments[0]

        if author == "BanchoBot":
            if message == "All players are ready":
                self.start_lobby(channel)
            elif message == "Countdown finished":
                self.resolve_countdown_finished(channel)
            elif message == "The match has started!":
                self.start_lobby_callback(channel)
            elif "finished playing" in message:
                player = message.split(" finished playing")[0]
                player = player.replace(" ", "_")
                self.change_map_lobby(player)
            elif "joined in slot 1" in message:
                player = message.split(" joined in slot")[0]
                player = player.replace(" ", "_")
                self.greet_player(player)
            elif "left the game." in message:
                player = message.split(" left the game")[0]
                player = player.replace(" ", "_")
                self.resolve_player_leave(player)
        else:
            if message == "!abort":
                self.abort_map(author=author)
            elif message == "!skip":
                self.skip_map(author=author)
            elif message == "!quit":
                self.close_match(author=author)
            elif message == "!play":
                self.start_lobby(channel)

    @staticmethod
    def lobby_decorator(function: Callable[[TryoutsBot, str], Any]):
        def wrapper(self, author: str) -> Any:
            if author in self.active_lobbies:
                lobby_details = self.active_lobbies.get(author)
                logger.debug(f"{function.__name__} called with: {lobby_details}")
                function(self, lobby_details)
                lobby_details_new = self.active_lobbies.get(author)
                logger.debug(
                    f"Lobby details after {function.__name__}: {lobby_details_new}"
                )
                return
            else:
                logger.warning(
                    f"{function.__name__} called with: {author} but active lobby could not be found!"
                )
                return

        return wrapper

    @lobby_decorator
    def abort_map(self, lobby_details: LobbyDetails):
        lobby_state = lobby_details.lobby_state
        lobby_channel = lobby_details.lobby_channel
        player = lobby_details.player
        if lobby_details.player_abort_count > 0:
            self.send(lobby_channel, self.settings["noAbortsLeft"])
            return
        if lobby_state == LobbyState.LOBBY_PLAYING:
            self.active_lobbies[player].player_abort_count += 1
            self.send(lobby_channel, "!mp abort")
            self.run_default_timer(lobby_channel, player)

    def add_player_to_sheet(self, message: str):
        player_name = message.split("(")[-1].split(")")[0]
        player_id = message.split("[")[-1].split("]")[0].split("/")[-1]
        player_sheet = PlayersSheet()
        player_sheet.add_player(player_id=player_id, player_name=player_name)

    def start_lobby(self, lobby_channel: str):
        """Start the lobby for the given channel"""
        self.send(lobby_channel, "!mp start 5")

    def start_lobby_callback(self, lobby_channel: str):
        """Lobby start callback received by BanchoBot that changes the lobby_state"""
        logger.info("Received lobby started callback, changing lobby state")
        for author, lobby_details in self.active_lobbies.items():
            if lobby_channel == lobby_details.lobby_channel:
                self.active_lobbies[author].lobby_state = LobbyState.LOBBY_PLAYING
                logger.info(f"Changed {author} lobby state to LOBBY_PLAYING")
                break

    def resolve_countdown_finished(self, lobby_channel):
        logger.info("Resolving the countdown finished event")
        player = None
        active_lobby = None
        for author, lobby_details in self.active_lobbies.items():
            if lobby_channel == lobby_details.lobby_channel:
                player = author
                active_lobby = lobby_details
                break

        if active_lobby.lobby_state == LobbyState.LOBBY_DISCONNECTED:
            logger.warning(
                f"{player} left the game and countdown ended. Terminating the game."
            )
            self.close_match(player)
        elif active_lobby.lobby_state == LobbyState.LOBBY_WAITING:
            logger.info(
                f"Countdown ended while {player} is in lobby. Starting the match."
            )
            self.start_lobby(lobby_channel=lobby_channel)

    @lobby_decorator
    def invite_lobby(self, lobby_details):
        """Invite player to lobby"""
        lobby_channel = lobby_details.lobby_channel
        player = lobby_details.player
        self.send(lobby_channel, f"!mp invite {player}")

    @lobby_decorator
    def skip_map(self, lobby_details: LobbyDetails):
        if lobby_details.lobby_state == LobbyState.LOBBY_PLAYING:
            self.send(lobby_details.lobby_channel, "!mp abort")
            self.change_to_next_map(lobby_details=lobby_details)
        elif (
            lobby_details.lobby_state == LobbyState.LOBBY_WAITING
            or lobby_details.lobby_state == LobbyState.LOBBY_INITIALIZED
        ):
            self.change_to_next_map(lobby_details=lobby_details)

    @lobby_decorator
    def change_map_lobby(self, lobby_details: LobbyDetails):
        player = lobby_details.player

        if lobby_details.lobby_state == LobbyState.LOBBY_PLAYING:
            self.change_to_next_map(lobby_details)

        logger.debug(
            f"Lobby details after changing map: {self.active_lobbies.get(player)}"
        )

    def change_to_next_map(self, lobby_details: LobbyDetails):
        player = lobby_details.player
        next_map_idx = lobby_details.next_map_idx

        if next_map_idx == len(self.mappool):
            logger.info("Exhausted all mappool, ending the lobby!")
            self.active_lobbies[player].lobby_state = LobbyState.LOBBY_ENDING
            self.close_match(player)
            return

        next_map = self.mappool[next_map_idx]

        logger.info(
            f"Changing the map for {lobby_details.player} to {next_map.beatmap_id}."
        )
        map_cmd, mod_cmd = next_map.to_multiplayer_cmd()
        self.send(lobby_details.lobby_channel, map_cmd)
        self.send(lobby_details.lobby_channel, mod_cmd)
        self.active_lobbies[lobby_details.player].next_map_idx += 1
        self.run_default_timer(lobby_details.lobby_channel, lobby_details.player)

    def run_default_timer(self, lobby_channel: str, player: str):
        self.send(lobby_channel, f"!mp timer {self.BEFORE_READY_WAIT_SECONDS}")
        self.active_lobbies[player].lobby_state = LobbyState.LOBBY_WAITING

    @lobby_decorator
    def resolve_player_leave(self, lobby_details: LobbyDetails):
        if lobby_details.player_leave_count < self.MAX_ALLOWED_LEAVES:
            self.send(
                lobby_details.lobby_channel, f"!mp timer {self.DISCONNECT_WAIT_TIMEOUT}"
            )
            self.active_lobbies[
                lobby_details.player
            ].lobby_state = LobbyState.LOBBY_DISCONNECTED
            self.active_lobbies[lobby_details.player].player_leave_count += 1
        else:
            author = lobby_details.player
            self.close_match(author=author)

    @lobby_decorator
    def greet_player(self, lobby_details: LobbyDetails):
        channel = lobby_details.lobby_channel
        player = lobby_details.player
        lobby_state = lobby_details.lobby_state
        if lobby_state == LobbyState.LOBBY_INITIALIZED:
            for greeting in self.settings["greetings"]:
                self.send(channel, greeting)
            self.active_lobbies[player].lobby_state = LobbyState.LOBBY_WAITING
        elif lobby_state == LobbyState.LOBBY_DISCONNECTED:
            disconnects_left = (
                self.MAX_ALLOWED_LEAVES - lobby_details.player_leave_count
            )
            self.active_lobbies[player].lobby_state = LobbyState.LOBBY_WAITING
            self.send(
                channel,
                self.settings["lobbyLeaveDetected"].format(
                    disconnects_left=disconnects_left,
                    player_leave_count=lobby_details.player_leave_count,
                    max_allowed_leaves=self.MAX_ALLOWED_LEAVES,
                ),
            )
            self.run_default_timer(lobby_channel=channel, player=player)

    def update_played_lobbies(self):
        players_sheet = PlayersSheet()
        players = players_sheet.get_players()
        lobby_sheet = TryoutLobbiesSheet()
        self.played_lobbies = lobby_sheet.get_played_lobbies(players)

    def make_lobby(self, author: str):
        self.update_played_lobbies()
        # Check tournament times
        time_now = datetime.datetime.now(tz=datetime.timezone.utc)
        if time_now < self.tournament_start:
            time_in_turkey = time_now + datetime.timedelta(hours=3)
            tournament_start_str = self.tournament_start.strftime("%Y-%m-%d %H:%M")
            self.send(
                author,
                self.settings["tournamentNotStartedYet"].format(
                    tournament_start_str=tournament_start_str,
                    time_in_turkey=time_in_turkey.strftime("%Y-%m-%d %H:%M"),
                ),
            )
            return
        elif time_now > self.tournament_end:
            tournament_end_str = self.tournament_end.strftime("%Y-%m-%d %H:%M")
            self.send(
                author,
                self.settings["tournamentEnded"].format(
                    tournament_end_str=tournament_end_str
                ),
            )
            if (
                author in self.played_lobbies
                or author.replace("_", " ") in self.played_lobbies
            ):
                lobby_urls = [lobby.lobby_url for lobby in self.played_lobbies[author]]
                lobby_urls_str = " - ".join(lobby_urls)
                self.send(
                    author,
                    self.settings["playerPlayedLobbies"].format(
                        lobby_urls_str=lobby_urls_str
                    ),
                )
            return
        # Check if player signed-up for the tournament
        if (
            len(self.allowed_players) > 0
            and (author not in self.allowed_players)
            and (author.replace("_", " ") not in self.allowed_players)
        ):
            self.send(author, self.settings["allowedPlayers"])
            return
        if author in self.active_lobbies:
            self.send(author, self.settings["playerAlreadyInLobby"])
            self.invite_lobby(author=author)
        elif (
            author in self.played_lobbies
            and len(self.played_lobbies[author]) >= self.MAX_ALLOWED_PLAYS
        ):
            lobby_urls = [lobby.lobby_url for lobby in self.played_lobbies[author]]
            lobby_urls_str = " - ".join(lobby_urls)
            self.send(
                author,
                self.settings["playerPlayedLobbies"].format(
                    lobby_urls_str=lobby_urls_str
                ),
            )
        else:
            self.last_lobby_requester = author
            self.send("BanchoBot", f"!mp make {self.tournament_name} - {author}")

    def parse_and_start_lobby(self, message: str):
        match_id = message.split("/")[-1].split(" ")[0]
        player = message.split(" ")[-1]
        lobby_url = f"https://osu.ppy.sh/community/matches/{match_id}"
        self.active_lobbies[player] = LobbyDetails(
            lobby_channel=f"#mp_{match_id}", lobby_url=lobby_url, player=player
        )
        logger.info(f"Started an active lobby: {self.active_lobbies.get(player)}")

        lobby_sheet = TryoutLobbiesSheet()
        lobby_sheet.append_lobby(lobby_url=lobby_url)
        self.request_player_info(player=player)

        self.setup_lobby(player)

    def request_player_info(self, player: str):
        self.send("BanchoBot", f"!stats {player}")

    def send(self, target: str, message: str):
        logger.info(f"Sending {message} to {target}")
        self.connection.privmsg(target, message)

    @lobby_decorator
    def setup_lobby(self, lobby_details: LobbyDetails):
        lobby_channel = lobby_details.lobby_channel
        current_map_idx = lobby_details.next_map_idx
        player = lobby_details.player

        current_map = self.mappool[current_map_idx]
        map_cmd, mod_cmd = current_map.to_multiplayer_cmd()

        self.send(lobby_channel, "!mp set 0 3 1")
        self.send(lobby_channel, f"!mp invite {player}")
        self.send(lobby_channel, map_cmd)
        self.send(lobby_channel, mod_cmd)

        self.active_lobbies[player].next_map_idx += 1
        self.active_lobbies[player].lobby_state = LobbyState.LOBBY_INITIALIZED

        logger.info(f"Lobby details after setup: {self.active_lobbies.get(player)}")

    @lobby_decorator
    def close_match(self, lobby_details):
        """Closes an active lobby."""
        lobby_channel = lobby_details.lobby_channel
        player = lobby_details.player
        self.send(lobby_channel, "!mp close")
        self.active_lobbies.pop(player)

    def cleanup(self):
        """Cleanup function that closes all the active lobbies."""
        players = [player for player in self.active_lobbies.keys()]
        for player in players:
            self.close_match(player)

    def _dispatcher(
        self, connection: irc.client.ServerConnection, event: irc.client.Event
    ):
        """
        Dispatch events to on_<event.type> method, if present.
        """
        if not event.type in self.ignored_events:
            logger.debug(f"{event}")

        def do_nothing(*args):
            return None

        method = getattr(self, "on_" + event.type, do_nothing)
        method(connection, event)
