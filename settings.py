import os


class Settings:
    def __init__(self):
        self.spreadsheet_id = os.getenv("SPREADSHEET_ID")
        self.spreadsheet_mappool_range = os.getenv("SPREADSHEET_MAPPOOL_RANGE")
        self.spreadsheet_tryout_scores_range = os.getenv("SPREADSHEET_TRYOUT_SCORES_RANGE")
        self.spreadsheet_tryout_lobbies_range = os.getenv("SPREADSHEET_TRYOUT_LOBBIES_RANGE")
        self.spreadsheet_players_range = os.getenv("SPREADSHEET_PLAYERS_RANGE")
        self.token_json_contents = os.getenv("TOKEN_JSON")

        self.log_level = os.getenv("LOG_LEVEL", "DEBUG").upper()

        self.irc_nickname = os.getenv("IRC_NICKNAME")
        self.irc_password = os.getenv("IRC_PASSWORD")

        self.environment = os.getenv("ENVIRONMENT", "prod").lower()
