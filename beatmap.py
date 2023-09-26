class Beatmap:
    def __init__(self, beatmap_id: str, mod: str):
        self.beatmap_id = beatmap_id
        self.mod = mod

    def __str__(self):
        return f"Beatmap {self.beatmap_id} played with {self.mod}"

    def __repr__(self):
        return f"{self.beatmap_id}-{self.mod}"

    def to_multiplayer_cmd(self):
        map_cmd = f"!mp map {self.beatmap_id}"
        if self.mod == "FM":
            mod_cmd = f"!mp mods 1 freemod"
        elif self.mod == "NM":
            mod_cmd = f"!mp mods NF"
        else:
            mod_cmd = f"!mp mods NF {self.mod}"
        return map_cmd, mod_cmd
