import math
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class OsuScore:
    player: str
    beatmap_id: str
    score: int
    z_score: Optional[float] = -10

    def __post_init__(self):
        self.score = int(self.score)

    def __iter__(self):
        return (self.__dict__[item] for item in self.__dict__)

    def __eq__(self, item):
        return self.beatmap_id == item

    def __lt__(self, other):
        return self.score < other

    def __gt__(self, other):
        return self.score > other

    def __add__(self, other):
        return self.score + other

    def __sub__(self, other):
        return self.score - other

    def __int__(self):
        return self.score

    def __radd__(self, other):
        return other + self.score

    def __rsub__(self, other):
        return self.score - other

    def calc_z(self, mean: float, stddev: float):
        self.z_score = (self.score - mean) / stddev
        return self.z_score


class BeatmapScores:
    def __init__(self, beatmap_id: str, scores: Optional[List[OsuScore]] = None):
        self.beatmap_id = beatmap_id
        self.scores = sorted(scores) if scores else []
        self.z_scores = self.calc_z()

    def add_score(self, score: OsuScore, tryout_players: Optional[List] = None):
        self.scores.append(score)
        self.scores.sort(reverse=True)
        self.z_scores = self.calc_z(tryout_players)

    def calc_z(self, tryout_players: Optional[List] = None) -> List[float]:
        if tryout_players:
            scores = [score for score in self.scores if score.player in tryout_players]
        else:
            scores = self.scores

        if len(scores) < 2:
            return []

        mean = sum(scores) / len(scores)

        mean_sq = sum([(score - mean) ** 2 for score in scores])
        stddev = math.sqrt(mean_sq / (len(scores) - 1))

        z_scores = [score.calc_z(mean, stddev) for score in scores]
        return z_scores

    def __iter__(self):
        return iter(self.scores)


class PlayerScores:
    def __init__(self, player: str, scores: Optional[List[OsuScore]] = None):
        self.player = player
        self.scores = sorted(scores) if scores else []

    def add_score(self, score: OsuScore):
        self.scores.append(score)
