from __future__ import print_function

import logging
import os.path
from collections import defaultdict
from typing import Union, List

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from beatmap import Beatmap
from lobbies import LobbyState, LobbyDetails
from settings import Settings

logger = logging.getLogger("tryouts-bot")

config = Settings()


class Spreadsheet:
    def __init__(self, spreadsheet_id, spreadsheet_range):
        self.scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
        ]
        self.spreadsheet_id = spreadsheet_id
        self.spreadsheet_range = spreadsheet_range

        if not os.path.exists("token.json"):
            logger.warning("Creating token.json with credentials from environment!")
            with open("token.json", "w") as f:
                f.write(config.token_json_contents)

        self.sheet = self.initialize()

    def initialize(self):
        creds = Credentials.from_authorized_user_file("token.json", self.scopes)
        service = build("sheets", "v4", credentials=creds)

        # Call the Sheets API
        sheet = service.spreadsheets()

        return sheet


class MappoolSpreadsheet(Spreadsheet):
    def __init__(
        self,
    ):
        super().__init__(
            config.mappool_spreadsheet_id, config.mappool_spreadsheet_range
        )

    def get_mappool(self):
        logger.info("Getting the mappool from sheets.")
        result = (
            self.sheet.values()
            .get(spreadsheetId=self.spreadsheet_id, range=self.spreadsheet_range)
            .execute(num_retries=5)
        )
        values = result.get("values", [])

        mappool = []
        for row in values:
            mappool.append(Beatmap(row[-1], row[0]))

        logger.info(f"Collected the mappool: {mappool}.")
        return mappool


class PlayersSheet(Spreadsheet):
    def __init__(
        self,
    ):
        super().__init__(
            config.stats_spreadsheet_id, config.stats_spreadsheet_players_range
        )

    def get_players(self):
        logger.info("Getting the players from sheets.")
        result = (
            self.sheet.values()
            .get(spreadsheetId=self.spreadsheet_id, range=self.spreadsheet_range)
            .execute(num_retries=5)
        )
        values = result.get("values", [])

        players = [v[1] for v in values]
        logger.info(f"Collected players: {players}.")
        return players

    def add_player(self, player_id: Union[str, int], player_name: str):
        row = [player_id, player_name, player_name]
        logger.info(f"Appending {row} to Players sheet.")
        res = (
            self.sheet.values()
            .append(
                spreadsheetId=self.spreadsheet_id,
                range=self.spreadsheet_range,
                valueInputOption="USER_ENTERED",
                body={"values": [row]},
            )
            .execute()
        )
        logger.info(f"Received: {res}")


class TryoutLobbiesSheet(Spreadsheet):
    def __init__(
        self,
    ):
        super().__init__(
            config.stats_spreadsheet_id, config.stats_spreadsheet_lobbies_range
        )

    def append_lobby(self, lobby_url):
        row = [lobby_url]
        logger.info(f"Appending {row} to TryoutLobbies sheet.")
        res = (
            self.sheet.values()
            .append(
                spreadsheetId=self.spreadsheet_id,
                range=self.spreadsheet_range,
                valueInputOption="USER_ENTERED",
                body={"values": [row]},
            )
            .execute()
        )
        logger.info(f"Received: {res}")

    def get_played_lobbies(self, players: List[str]):
        logger.info("Getting the tryout lobbies from sheets.")
        result = (
            self.sheet.values()
            .get(spreadsheetId=self.spreadsheet_id, range=self.spreadsheet_range)
            .execute(num_retries=5)
        )

        values = result.get("values", [])

        lobbies = defaultdict(list)
        for row, player_name in zip(values, players):
            match_url = row[0]
            match_id = match_url.split("/")[-1]
            lobbies[player_name].append(
                LobbyDetails(
                    lobby_channel=f"#mp_{match_id}",
                    lobby_url=match_url,
                    player=player_name,
                    next_map_idx=0,
                    lobby_state=LobbyState.LOBBY_ENDING,
                )
            )

        return lobbies
