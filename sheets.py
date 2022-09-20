from __future__ import print_function

import logging
import os.path

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from beatmap import Beatmap
from lobbies import LobbyState, LobbyDetails
from settings import Settings

logger = logging.getLogger("tryouts-bot")

config = Settings()


class Spreadsheet:

    def __init__(self, spreadsheet_id, spreadsheet_range):
        self.scopes = ['https://www.googleapis.com/auth/spreadsheets', ]
        self.spreadsheet_id = spreadsheet_id
        self.spreadsheet_range = spreadsheet_range

        if not os.path.exists('token.json'):
            logger.warning("Creating token.json with credentials from environment!")
            with open('token.json', 'w') as f:
                f.write(config.token_json_contents)

        self.sheet = self.initialize()

    def initialize(self):
        creds = Credentials.from_authorized_user_file('token.json', self.scopes)
        service = build('sheets', 'v4', credentials=creds)

        # Call the Sheets API
        sheet = service.spreadsheets()

        return sheet


class MappoolSpreadsheet(Spreadsheet):
    def __init__(self, ):
        super().__init__(config.spreadsheet_id, config.spreadsheet_mappool_range)

    def get_mappool(self):
        logger.info("Getting the mappool from sheets.")
        result = self.sheet.values().get(spreadsheetId=self.spreadsheet_id,
                                         range=self.spreadsheet_range).execute()
        values = result.get('values', [])

        mappool = []
        for row in values:
            mappool.append(Beatmap(row[-1], row[5]))

        logger.info(f"Collected the mappool: {mappool}.")
        return mappool


class TryoutScoresSheet(Spreadsheet):
    def __init__(self, ):
        super().__init__(config.spreadsheet_id, config.spreadsheet_tryout_scores_range)

    def append_score(self, player: str, score: str, beatmap_id: str):
        row = [player, beatmap_id, score]
        logger.info(f"Appending {row} to TryoutScores sheet.")
        res = self.sheet.values().append(spreadsheetId=self.spreadsheet_id,
                                         range=self.spreadsheet_range,
                                         valueInputOption="USER_ENTERED",
                                         insertDataOption="INSERT_ROWS",
                                         body={"values": [row]}).execute()
        logger.info(f"Received: {res}")


class TryoutLobbiesSheet(Spreadsheet):
    def __init__(self, ):
        super().__init__(config.spreadsheet_id, config.spreadsheet_tryout_lobbies_range)

    def append_lobby(self, player, lobby_url):
        row = [player, lobby_url]
        logger.info(f"Appending {row} to TryoutLobbies sheet.")
        res = self.sheet.values().append(spreadsheetId=self.spreadsheet_id,
                                         range=self.spreadsheet_range,
                                         valueInputOption="USER_ENTERED",
                                         insertDataOption="INSERT_ROWS",
                                         body={"values": [row]}).execute()
        logger.info(f"Received: {res}")

    def get_played_lobbies(self):
        logger.info("Getting the tryout lobbies from sheets.")
        result = self.sheet.values().get(spreadsheetId=self.spreadsheet_id,
                                         range=self.spreadsheet_range).execute()
        values = result.get('values', [])

        lobbies = {}
        for row in values:
            player = row[0]
            match_url = row[1]
            match_id = match_url.split("/")[-1]
            lobbies[player] = LobbyDetails(lobby_channel=f"#mp_{match_id}",
                                           lobby_url=match_url,
                                           player=player,
                                           map_idx=0,
                                           lobby_state=LobbyState.LOBBY_ENDING)

        return lobbies
