import logging

from irc_bot import TryoutsBot
from settings import Settings
from sheets import MappoolSpreadsheet, PlayersSheet

config = Settings()

logger = logging.getLogger("tryouts-bot")
logger.setLevel(config.log_level)

ch = logging.StreamHandler()
formatter = logging.Formatter(
    '%(asctime)s | %(levelname)s | %(process)d | %(name)s | %(funcName)s | %(message)s',
    datefmt='%d/%m/%Y %I:%M:%S')
ch.setFormatter(formatter)

logger.addHandler(ch)

if __name__ == '__main__':
    mappool_sheet = MappoolSpreadsheet()
    mappool = mappool_sheet.get_mappool()
    players_sheet = PlayersSheet()
    players = players_sheet.get_players()

    if config.environment == "testing":
        mappool = [mappool[1], mappool[5], mappool[7], mappool[9]]

    bot = TryoutsBot(nickname=config.irc_nickname,
                     password=config.irc_password,
                     mappool=mappool,
                     allowed_players=players)
    try:
        bot.start()
    except BaseException as e:
        logger.exception(e)
        bot.cleanup()
