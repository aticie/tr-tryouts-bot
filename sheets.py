from __future__ import print_function

import logging
import os.path
from collections import defaultdict
from typing import List

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from beatmap import Beatmap
from lobbies import LobbyState, LobbyDetails
from score import OsuScore, BeatmapScores
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

    def get_scores(self) -> List[OsuScore]:
        result = self.sheet.values().get(spreadsheetId=self.spreadsheet_id,
                                         range=self.spreadsheet_range).execute()
        values = result.get('values', [])
        return [OsuScore(*row) for row in values]

    def migrate_to_results_sheet(self):
        tryout_players = ["-Kemsyt", "egemenbsrms", "emptypudding", "ErAlpha", "Ievi-", "KaraElmas", "LyeRR", "Misora-",
                          "Nymphe", "Orkay", "pottomotto22", "Rosaitty", "Sekjiru", "Serdar", "Shinkiro", "shorion",
                          "SStoney", "suioji", "SunoExy", "y4kr3b", "Yoani"]

        scores = self.get_scores()

        beatmap_ids_result = self.sheet.values().get(spreadsheetId=self.spreadsheet_id,
                                                     range="TryoutResults!L2:BG2").execute()
        beatmap_ids = list(filter(None, beatmap_ids_result.get('values', [])[0]))

        all_players = {score.player for score in scores}

        beatmap_scores = []
        for beatmap_id in beatmap_ids:
            bs = BeatmapScores(beatmap_id)
            [bs.add_score(score, tryout_players) for score in scores if score.beatmap_id == beatmap_id]
            beatmap_scores.append(bs)

        overall_z = [[""] * 2 for _ in range(14)]
        total_z = defaultdict(int)
        for score in scores:
            total_z[score.player] += score.z_score

        for i, (player, score) in enumerate(total_z.items()):
            overall_z[i][:] = (player, score)

        # Construct inserted rows
        rows = [[""] * 3 * len(beatmap_ids) for _ in range(len(all_players))]
        for beatmap_idx, score_col in enumerate(beatmap_scores):
            for score_idx, score in enumerate(score_col):
                beatmap_idx = beatmap_ids.index(score.beatmap_id)
                rows[score_idx][beatmap_idx * 3] = score.player
                rows[score_idx][beatmap_idx * 3 + 1] = score.score
                rows[score_idx][beatmap_idx * 3 + 2] = score.z_score

        mod_idx = [range(6), range(6, 9), range(9, 12), range(12, 16)]
        modz_rows = [[""] * 2 * len(mod_idx) for _ in range(len(all_players))]
        for mod_i, mod_range in enumerate(mod_idx):
            mod_z_scores = {}
            for beatmap_idx in mod_range:
                scores = beatmap_scores[beatmap_idx]
                scores.calc_z(tryout_players)

                for score in scores:
                    if score.player in mod_z_scores:
                        mod_z_scores[score.player] += score.z_score
                    else:
                        mod_z_scores[score.player] = score.z_score

            modz = tuple(mod_z_scores.items())
            for player_i, player_score in enumerate(modz):
                modz_rows[player_i][mod_i * 2:mod_i * 2 + 2] = player_score

        self.sheet.values().update(spreadsheetId=self.spreadsheet_id,
                                   range="TryoutResults!L3:BG16",
                                   valueInputOption="USER_ENTERED",
                                   body={"values": rows}).execute()

        self.sheet.values().update(spreadsheetId=self.spreadsheet_id,
                                   range="TryoutResults!D3:K16",
                                   valueInputOption="USER_ENTERED",
                                   body={"values": modz_rows}).execute()

        self.sheet.values().update(spreadsheetId=self.spreadsheet_id,
                                   range="TryoutResults!B3:D16",
                                   valueInputOption="USER_ENTERED",
                                   body={"values": overall_z}).execute()


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

        lobbies = defaultdict(list)
        for row in values:
            player = row[0]
            match_url = row[1]
            match_id = match_url.split("/")[-1]
            lobbies[player].append(LobbyDetails(lobby_channel=f"#mp_{match_id}",
                                                lobby_url=match_url,
                                                player=player,
                                                map_idx=0,
                                                lobby_state=LobbyState.LOBBY_ENDING))

        return lobbies


if __name__ == '__main__':
    sheet = TryoutScoresSheet()
    sheet.migrate_to_results_sheet()
