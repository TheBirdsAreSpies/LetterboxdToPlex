import json
import os
import config


class Mapping:
    def __init__(self, letterboxd_title, plex_title):
        self.letterboxd_title = letterboxd_title
        self.plex_title = plex_title


    @staticmethod
    def load_json():
        if os.path.exists(config.mapping_path):
            with open(config.mapping_path, 'r', encoding='utf-8') as file:
                json_data = file.read()
                data_list = json.loads(json_data)

                items = []
                for data in data_list:
                    item = Mapping(data["letterboxd_title"], data["plex_title"])
                    items.append(item)

                return items

    @staticmethod
    def store_json(items):
        serialized_data = json.dumps([i.__dict__ for i in items], indent=3)
        with open(config.mapping_path, 'w') as file:
            file.write(serialized_data)
