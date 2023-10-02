import json
import os
import config


class Mapping:
    def __init__(self, letterboxd_title, plex_title, year):
        self.letterboxd_title = letterboxd_title
        self.plex_title = plex_title
        self.year = year


    @staticmethod
    def load_json():
        if os.path.exists(config.mapping_path):
            with open(config.mapping_path, 'r', encoding='utf-8') as file:
                json_data = file.read()
                data_list = json.loads(json_data)

                items = []
                for data in data_list:
                    if 'year' in data:
                        item = Mapping(data["letterboxd_title"], data["plex_title"], data["year"])
                    else:
                        item = Mapping(data["letterboxd_title"], data["plex_title"], -1)
                    items.append(item)

                return items

    @staticmethod
    def store_json(items):
        serialized_data = json.dumps([i.__dict__ for i in items], indent=3)
        with open(config.mapping_path, 'w') as file:
            file.write(serialized_data)
