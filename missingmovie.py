import config
import json
import os
from movie import Movie


class MissingMovie(Movie):
    @staticmethod
    def load_json():
        if os.path.exists(config.missing_path):
            with open(config.missing_path, 'r', encoding='utf-8') as file:
                json_data = file.read()
                data_list = json.loads(json_data)

                items = []
                for data in data_list:
                    item = MissingMovie(data["name"], data["year"])
                    items.append(item)

                return items

    @staticmethod
    def store_json(items):
        serialized_data = json.dumps([i.__dict__ for i in items], indent=3)
        with open(config.missing_path, 'w') as file:
            file.write(serialized_data)