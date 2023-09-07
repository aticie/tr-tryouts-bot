from __future__ import annotations

import datetime
import logging
from typing import List, Callable, Any, Dict

import irc
import irc.bot
import irc.client

from beatmap import Beatmap
from lobbies import LobbyState, LobbyDetails
from sheets import TryoutLobbiesSheet, TryoutScoresSheet

logger = logging.getLogger("tryouts-bot")


class TryoutsBot(irc.bot.SingleServerIRCBot):
    MAX_ALLOWED_LEAVES = 3

    def __init__(self, nickname: str, password: str, mappool: List[Beatmap], tournament_name: str = "H1A Qualifiers",
                 allowed_players: List[str] = None):
        logger.debug(f"TryoutsBot initating: {nickname} {password} {mappool}")
        irc.bot.SingleServerIRCBot.__init__(self, [("irc.ppy.sh", 6667, password)], nickname, nickname)

        self.recon = irc.bot.ExponentialBackoff(min_interval=5, max_interval=30)

        self.tournament_start = datetime.datetime(year=2023, month=9, day=7, hour=20, minute=59, second=59, tzinfo=datetime.timezone.utc)
        self.tournament_end = datetime.datetime(year=2023, month=9, day=17, hour=20, minute=59, second=59, tzinfo=datetime.timezone.utc)

        self.ignored_events = ["all_raw_messages", "quit"]

        self.mappool = mappool
        if allowed_players is None:
            self.allowed_players = []
        else:
            self.allowed_players = allowed_players

        self.last_lobby_requester = ""

        self.tournament_name = tournament_name

        self.active_lobbies: Dict[str, LobbyDetails] = {}
        self.played_lobbies: Dict[str, List[LobbyDetails]] = {}
        self.connection.set_rate_limit(1)

    def _on_kick(self, connection: irc.client.ServerConnection, event: irc.client.Event):
        logger.debug(f"{event}")
        channel = event.target

        player_to_be_removed = None
        for player, lobby_details in self.active_lobbies.items():
            if lobby_details.lobby_channel == channel:
                player_to_be_removed = player

        if player_to_be_removed:
            logger.debug(f"Removing {player_to_be_removed} from active lobbies because we are kicked?")
            self.active_lobbies.pop(player_to_be_removed)
        else:
            logger.debug(f"We are kicked but I couldn't find the active lobby. The lobbies were: {self.active_lobbies}")

    def on_privmsg(self, connection: irc.client.ServerConnection, event: irc.client.Event):
        """Receive a privmsg event

        Handles a privmsg event. Calls the corresponding function depending on the message.
        If the message is:
        - !q: Handle queue command. Start a private lobby for the player.
        """
        logger.debug(f"{event}")
        author = event.source.nick
        message = event.arguments[0]

        if author == "BanchoBot":
            if message.startswith("Created the tournament"):
                self.parse_and_start_lobby(message=message)
            elif message.startswith("You cannot create any more tournament matches."):
                self.send(self.last_lobby_requester, f"Bütün lobiler şu anda dolu, lütfen daha sonra tekrar deneyin.")
        else:
            if message == "!play":
                self.make_lobby(author=author)
            elif message == "!invite":
                self.invite_lobby(author=author)

    def on_pubmsg(self, connection: irc.client.ServerConnection, event: irc.client.Event):
        """Receive a pubmsg event

        Handles a pubmsg event. Calls the corresponding function depending on the message.
        If the message is from BanchoBot:
        - Start the lobby if timer ends or player readies up
        """
        logger.debug(f"{event}")
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
                player = message.split(" ")[0]
                self.send_scores_to_sheet(message)
                self.change_map_lobby(player)
            elif "joined in slot 1" in message:
                player = message.split(" ")[0]
                self.greet_player(player)
            elif "left the game." in message:
                player = message.split(" ")[0]
                self.resolve_player_leave(player)
        else:
            if message == "!abort":
                self.abort_lobby(author=author)
            elif message == "!quit":
                self.close_match(author=author)

    @staticmethod
    def lobby_decorator(function: Callable[[TryoutsBot, str], Any]):
        def wrapper(self, author: str) -> Any:
            if author in self.active_lobbies:
                lobby_details = self.active_lobbies.get(author)
                logger.debug(f"{function.__name__} called with: {lobby_details}")
                function(self, lobby_details)
                lobby_details_new = self.active_lobbies.get(author)
                logger.debug(f"Lobby details after {function.__name__}: {lobby_details_new}")
                return
            else:
                logger.warning(f"{function.__name__} called with: {author} but active lobby could not be found!")
                return

        return wrapper

    @lobby_decorator
    def abort_lobby(self, lobby_details: LobbyDetails):
        lobby_state = lobby_details.lobby_state
        lobby_channel = lobby_details.lobby_channel
        player = lobby_details.player
        if lobby_details.player_abort_count > 0:
            self.send(lobby_channel, "Abort hakkınız kalmadı.")
            return
        if lobby_state == LobbyState.LOBBY_PLAYING:
            self.active_lobbies[player].player_abort_count += 1
            self.send(lobby_channel, "!mp abort")
            self.run_default_timer(lobby_channel, player)

    def start_lobby(self, lobby_channel: str):
        """Start the lobby for the given channel"""
        self.send(lobby_channel, "!mp start 7")

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
            logger.warning(f"{player} left the game and countdown ended. Terminating the game.")
            self.close_match(player)
        elif active_lobby.lobby_state == LobbyState.LOBBY_WAITING:
            logger.info(f"Countdown ended while {player} is in lobby. Starting the match.")
            self.start_lobby(lobby_channel=lobby_channel)

    @lobby_decorator
    def invite_lobby(self, lobby_details):
        """Invite player to lobby"""
        lobby_channel = lobby_details.lobby_channel
        player = lobby_details.player
        self.send(lobby_channel, f"!mp invite {player}")

    @lobby_decorator
    def change_map_lobby(self, lobby_details):
        lobby_channel = lobby_details.lobby_channel
        player = lobby_details.player
        map_idx = lobby_details.map_idx

        if map_idx == len(self.mappool):
            logger.info("Exhausted all mappool, ending the lobby!")
            self.active_lobbies[player].lobby_state = LobbyState.LOBBY_ENDING
            self.close_match(player)
            return

        if lobby_details.lobby_state == LobbyState.LOBBY_PLAYING:
            current_map = self.mappool[map_idx]
            logger.info(f"Changing the map for {player} to {current_map.beatmap_id}.")
            map_cmd, mod_cmd = current_map.to_multiplayer_cmd()

            self.send(lobby_channel, map_cmd)
            self.send(lobby_channel, mod_cmd)
            self.active_lobbies[player].map_idx += 1
            self.run_default_timer(lobby_channel, player)

        logger.debug(f"Lobby details after changing map: {self.active_lobbies.get(player)}")

    def run_default_timer(self, lobby_channel: str, player: str):
        self.send(lobby_channel, "!mp timer 120")
        self.active_lobbies[player].lobby_state = LobbyState.LOBBY_WAITING

    @lobby_decorator
    def resolve_player_leave(self, lobby_details: LobbyDetails):
        if lobby_details.player_leave_count < self.MAX_ALLOWED_LEAVES:
            self.send(lobby_details.lobby_channel, "!mp timer 300")
            self.active_lobbies[lobby_details.player].lobby_state = LobbyState.LOBBY_DISCONNECTED
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
            self.send(channel, "heyronii'nin 1-A Sınıfı osu! Turnuvası'na hoşgeldiniz!")
            self.send(channel, "Oyunda aksaklık yaşarsanız !abort durdurabilirsiniz (1 kere ile sınırlıdır).")
            self.send(channel, "İlk mapi hazır olduğunuzda başlatacağım.")
            self.active_lobbies[player].lobby_state = LobbyState.LOBBY_WAITING
        elif lobby_state == LobbyState.LOBBY_DISCONNECTED:
            disconnects_left = self.MAX_ALLOWED_LEAVES - lobby_details.player_leave_count
            self.active_lobbies[player].lobby_state = LobbyState.LOBBY_WAITING
            self.send(channel,
                      f"Lobiden ayrıldığınız tespit edildi. {disconnects_left} "
                      f"kere daha ayrılmanız durumunda maçınız sonlandırılacktır. "
                      f"({lobby_details.player_leave_count}/{self.MAX_ALLOWED_LEAVES})")
            self.run_default_timer(lobby_channel=channel,
                                   player=player)

    def update_played_lobbies(self):
        lobby_sheet = TryoutLobbiesSheet()
        self.played_lobbies = lobby_sheet.get_played_lobbies()

    def make_lobby(self, author: str):
        # Check tournament times
        time_now = datetime.datetime.now(tz=datetime.timezone.utc)
        if time_now < self.tournament_start:
            time_in_turkey = time_now + datetime.timedelta(hours=3)
            self.send(author, f"Turnuva henüz başlamadı. 7 Eylül 23:59'dan sonra başlayacak. Şu anda saat: {time_in_turkey.strftime('%H:%M')}")
            return
        elif time_now > self.tournament_end:
            self.send(author, "Turnuva 17 Eylül 23:59 tarihinde sona erdi.")
            if author in self.played_lobbies:
                lobby_urls = [lobby.lobby_url for lobby in self.played_lobbies[author]]
                self.send(author, f"Oynamış olduğunuz lobiler: {' - '.join(lobby_urls)}")

        # Check if player signed-up for the tournament
        if (len(self.allowed_players) > 0) and (author not in self.allowed_players):
            self.send(author, "Bu bot sadece heyronii'nin 1-A Sınıfı "
                              "osu! Turnuvasına katılanlar tarafından kullanılabilir.")
            return
        self.update_played_lobbies()
        if author in self.active_lobbies:
            self.send(author, "Şu anda bir lobidesiniz, size davet gönderiyorum.")
            self.invite_lobby(authro=author)
        elif (author in self.played_lobbies and
              len(self.played_lobbies[author]) > 1):
            lobby_urls = [lobby.lobby_url for lobby in self.played_lobbies[author]]
            self.send(author, f"Oynamış olduğunuz lobiler: {' - '.join(lobby_urls)}")
        else:
            self.last_lobby_requester = author
            self.send("BanchoBot", f"!mp make {self.tournament_name} - {author}")

    def parse_and_start_lobby(self, message: str):
        match_id = message.split("/")[-1].split(" ")[0]
        player = message.split(" ")[-1]
        lobby_url = f"https://osu.ppy.sh/community/matches/{match_id}"
        self.active_lobbies[player] = LobbyDetails(lobby_channel=f"#mp_{match_id}",
                                                   lobby_url=lobby_url,
                                                   player=player)
        logger.info(f"Started an active lobby: {self.active_lobbies.get(player)}")

        lobby_sheet = TryoutLobbiesSheet()
        lobby_sheet.append_lobby(player, lobby_url=lobby_url)

        self.setup_lobby(player)

    def send(self, target: str, message: str):
        logger.info(f"Sending {message} to {target}")
        self.connection.privmsg(target, message)

    @lobby_decorator
    def setup_lobby(self, lobby_details: LobbyDetails):
        lobby_channel = lobby_details.lobby_channel
        current_map_idx = lobby_details.map_idx
        player = lobby_details.player

        current_map = self.mappool[current_map_idx]
        map_cmd, mod_cmd = current_map.to_multiplayer_cmd()

        self.send(lobby_channel, "!mp set 0 3 1")
        self.send(lobby_channel, f"!mp invite {player}")
        self.send(lobby_channel, map_cmd)
        self.send(lobby_channel, mod_cmd)

        self.active_lobbies[player].map_idx += 1
        self.active_lobbies[player].lobby_state = LobbyState.LOBBY_INITIALIZED

        logger.info(f"Lobby details after setup: {self.active_lobbies.get(player)}")

    @lobby_decorator
    def close_match(self, lobby_details):
        """Closes an active lobby."""
        lobby_channel = lobby_details.lobby_channel
        player = lobby_details.player
        self.send(lobby_channel, "!mp close")
        self.active_lobbies.pop(player)

    def send_scores_to_sheet(self, message: str):
        player = message.split(" ")[0]
        score = message.split("Score: ")[-1].split(",")[0]

        map_idx = self.active_lobbies[player].map_idx - 1  # -1 because we incremented once after changing map.
        beatmap = self.mappool[map_idx]

        logger.info(f"Sending [{player}, {score}, {beatmap.beatmap_id}] to TryoutScoresSheet.")
        sheet = TryoutScoresSheet()
        sheet.append_score(player=player,
                           score=score,
                           beatmap_id=beatmap.beatmap_id)

    def cleanup(self):
        """Cleanup function that closes all the active lobbies."""
        players = [player for player in self.active_lobbies.keys()]
        for player in players:
            self.close_match(player)

    def _dispatcher(self, connection: irc.client.ServerConnection, event: irc.client.Event):
        """
        Dispatch events to on_<event.type> method, if present.
        """
        if not event.type in self.ignored_events:
            logger.debug(f"{event}")

        def do_nothing(*args):
            return None

        method = getattr(self, "on_" + event.type, do_nothing)
        method(connection, event)
