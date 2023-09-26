import os


class Settings:
    def __init__(self):
        self.mappool_spreadsheet_id = os.getenv("MAPPOOL_SPREADSHEET_ID")
        self.mappool_spreadsheet_range = os.getenv("MAPPOOL_SPREADSHEET_RANGE")
        self.stats_spreadsheet_id = os.getenv("STATS_SPREADSHEET_ID")
        self.stats_spreadsheet_lobbies_range = os.getenv(
            "STATS_SPREADSHEET_LOBBIES_RANGE"
        )
        self.stats_spreadsheet_players_range = os.getenv(
            "STATS_SPREADSHEET_PLAYERS_RANGE"
        )
        self.token_json_contents = os.getenv("TOKEN_JSON")

        self.log_level = os.getenv("LOG_LEVEL", "DEBUG").upper()

        self.irc_nickname = os.getenv("IRC_NICKNAME")
        self.irc_password = os.getenv("IRC_PASSWORD")

        self.environment = os.getenv("ENVIRONMENT", "prod").lower()
