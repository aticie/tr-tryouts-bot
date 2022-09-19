import logging
import sys
from typing import List, Dict

import irc
import irc.bot
import irc.client

from beatmap import Beatmap
from lobby import Lobby
from sheets import TryoutLobbiesSheet, TryoutScoresSheet

logger = logging.getLogger("tryouts-bot")


class TryoutsBot(irc.bot.SingleServerIRCBot):
    def __init__(self, nickname: str, password: str, mappool: List[Beatmap]):
        irc.bot.SingleServerIRCBot.__init__(self, [("irc.ppy.sh", 6667, password)], nickname, nickname)

        self.mappool = mappool

        self.active_lobbies = {}
        self.connection.set_rate_limit(1)

    def _on_kick(self, connection: irc.client.ServerConnection, event: irc.client.Event):
        logger.debug(f"{event}")
        channel = event.target

        player_to_be_removed = None
        for player, lobby_details in self.active_lobbies.items():
            if lobby_details["lobby_channel"] == channel:
                player_to_be_removed = player

        if player_to_be_removed:
            logger.debug(f"Removing {player_to_be_removed} from active lobbies because we are kicked?")
            self.active_lobbies.pop(player_to_be_removed)
        else:
            logger.debug(f"We are kicked but I couldn't find the active lobby. The lobbies were: {self.active_lobbies}")

    def on_welcome(self, connection: irc.client.ServerConnection, event: irc.client.Event):
        logger.debug(f"{event}")

    def on_privmsg(self, connection: irc.client.ServerConnection, event: irc.client.Event):
        """Receive a privmsg event

        Handles a privmsg event. Calls the corresponding function depending on the message.
        If the message is:
        - !q: Handle queue command. Start a private lobby for the player.
        - !pause: Handle pause command. Pause the lobby of the player.
        """
        logger.debug(f"{event}")
        author = event.source.nick
        message = event.arguments[0]

        if author == "BanchoBot":
            if message.startswith("Created the tournament"):
                self.parse_and_start_lobby(message=message)
        else:
            if message == "!q":
                self.make_lobby(author=author)
            elif message == "!pause":
                self.pause_lobby(author=author)
            elif message == "!invite":
                self.invite_lobby(author=author)

    def on_pubmsg(self, connection: irc.client.ServerConnection, event: irc.client.Event):
        """Receive a pubmsg event

        Handles a pubmsg event. Calls the corresponding function depending on the message.
        If the message is from BanchoBot:
        - Start the lobby if timer ends or player readies up
        If the message is from player:
        - Pause the game until player readies up.
        """
        logger.debug(f"{event}")
        author = event.source.nick
        channel = event.target
        message = event.arguments[0]

        if author == "BanchoBot":
            if message == "All players are ready" or message == "Countdown finished":
                self.start_lobby(channel)
            elif message == "The match has started!":
                self.start_lobby_callback(channel)
            elif "finished playing" in message:
                player = message.split(" ")[0]
                self.send_scores_to_sheet(message)
                self.change_map_lobby(player)
            elif "joined in slot 1" in message:
                self.send(channel, "Welcome to OWC Turkey tryouts!")
                self.send(channel, "I will start the lobby when you are ready.")
                self.send(channel, "Use !pause anytime to pause the timer.")
                self.send(channel, "Use !abort if you have trouble in-game (don't abuse this).")
        else:
            if message == "!pause":
                self.pause_lobby(author=author)
            elif message == "!abort":
                self.abort_lobby(author=author)
            elif message == "!quit":
                self.close_match(author=author)

    @staticmethod
    def lobby_decorator(function):
        def wrapper(self, author: str):
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
    def abort_lobby(self, lobby_details: Dict):
        lobby_state = lobby_details["lobby_state"]
        lobby_channel = lobby_details["lobby_channel"]
        player = lobby_details["player"]
        if lobby_state == Lobby.LOBBY_PLAYING:
            self.send(lobby_channel, "!mp abort")
            self.send(lobby_channel, "!mp timer 120")
            self.active_lobbies[player]["lobby_state"] = Lobby.LOBBY_WAITING

    def start_lobby(self, lobby_channel: str):
        """Start the lobby for the given channel"""
        self.send(lobby_channel, "!mp start 7")

    def start_lobby_callback(self, lobby_channel: str):
        """Lobby start callback received by BanchoBot that changes the lobby_state"""
        logger.info("Received lobby started callback, changing lobby state")
        for author, lobby_details in self.active_lobbies.items():
            if lobby_channel == lobby_details["lobby_channel"]:
                self.active_lobbies[author]["lobby_state"] = Lobby.LOBBY_PLAYING
                logger.info(f"Changed {author} lobby state to LOBBY_PLAYING")
                break

    @lobby_decorator
    def invite_lobby(self, lobby_details: Dict):
        """Invite player to lobby"""
        lobby_channel = lobby_details["lobby_channel"]
        player = lobby_details["player"]
        self.send(lobby_channel, f"!mp invite {player}")

    @lobby_decorator
    def pause_lobby(self, lobby_details: Dict):
        lobby_channel = lobby_details["lobby_channel"]
        self.send(lobby_channel, "!mp aborttimer")
        self.send(lobby_channel, "Waiting for you to be ready!")

    @lobby_decorator
    def change_map_lobby(self, lobby_details: Dict):
        lobby_channel = lobby_details["lobby_channel"]
        player = lobby_details["player"]
        map_idx = lobby_details["map_idx"]

        if map_idx == len(self.mappool):
            logger.info("Exhausted all mappool, ending the lobby!")
            self.active_lobbies[player]["lobby_state"] = Lobby.LOBBY_ENDING
            self.close_match(player)

        if lobby_details["lobby_state"] == Lobby.LOBBY_PLAYING:
            current_map = self.mappool[map_idx]
            logger.info(f"Changing the map for {player} to {current_map.beatmap_id}.")
            map_cmd, mod_cmd = current_map.to_multiplayer_cmd()

            self.send(lobby_channel, map_cmd)
            self.send(lobby_channel, mod_cmd)
            self.send(lobby_channel, "!mp timer 120")
            self.active_lobbies[player]["map_idx"] += 1
            self.active_lobbies[player]["lobby_state"] = Lobby.LOBBY_WAITING

        logger.debug(f"Lobby details after changing map: {self.active_lobbies[player]}")

    def make_lobby(self, author: str):
        if author not in self.active_lobbies:
            self.send("BanchoBot", f"!mp make OWCTR-Tryouts {author}")
            self.active_lobbies[author] = {}
        else:
            self.send(author, "You already have an active lobby. Sending you a new invite!")
            self.invite_lobby(author)

    def parse_and_start_lobby(self, message: str):
        match_id = message.split("/")[-1].split(" ")[0]
        player = message.split(" ")[-1]
        lobby_url = f"https://osu.ppy.sh/community/matches/{match_id}"
        self.active_lobbies[player] = {"lobby_channel": f"#mp_{match_id}",
                                       "lobby_url": lobby_url,
                                       "player": f"{player}",
                                       "map_idx": 0,
                                       "lobby_state": Lobby.LOBBY_STARTED}
        logger.info(f"Started an active lobby: {self.active_lobbies[player]}")

        lobby_sheet = TryoutLobbiesSheet()
        lobby_sheet.append_lobby(player, lobby_url=lobby_url)

        self.setup_lobby(player)

    def send(self, target: str, message: str):
        logger.info(f"Sending {message} to {target}")
        self.connection.privmsg(target, message)

    @lobby_decorator
    def setup_lobby(self, lobby_details: Dict):
        lobby_channel = lobby_details["lobby_channel"]
        current_map_idx = lobby_details["map_idx"]
        player = lobby_details["player"]

        current_map = self.mappool[current_map_idx]
        map_cmd, mod_cmd = current_map.to_multiplayer_cmd()

        self.send(lobby_channel, "!mp set 0 3 1")
        self.send(lobby_channel, f"!mp invite {player}")
        self.send(lobby_channel, map_cmd)
        self.send(lobby_channel, mod_cmd)

        self.active_lobbies[player]["map_idx"] += 1
        self.active_lobbies[player]["lobby_state"] = Lobby.LOBBY_WAITING

        logger.info(f"Lobby details after setup: {self.active_lobbies[player]}")

    @lobby_decorator
    def close_match(self, lobby_details: Dict):
        """Closes an active lobby."""
        lobby_channel = lobby_details["lobby_channel"]
        player = lobby_details["player"]
        self.send(lobby_channel, "!mp close")
        self.active_lobbies.pop(player)

    def send_scores_to_sheet(self, message: str):
        player = message.split(" ")[0]
        score = message.split("Score: ")[-1].split(",")[0]

        map_idx = self.active_lobbies[player]["map_idx"] - 1  # -1 because we incremented once after changing map.
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

    def on_disconnect(self, connection: irc.client.ServerConnection, event: irc.client.Event):
        logger.info(f"on_disconnect: {event}")
        sys.exit(0)
