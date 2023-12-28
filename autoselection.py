import json
import os
import config
from movie import Movie


class AutoSelection:
    def __init__(self, combination, movie_to_prefer_key):
        self.combination = combination
        self.movie_to_prefer_key = movie_to_prefer_key

    def to_json(self):
        return {
            'combination': {
                'name': self.combination.name,
                'year': self.combination.year
            },
            'movie_to_prefer_key': self.movie_to_prefer_key
        }

    @staticmethod
    def load_json():
        if os.path.exists(config.autoselection_path):
            with open(config.autoselection_path, 'r', encoding='utf-8') as file:
                json_data = file.read()
                data_list = json.loads(json_data)

                mapping = []
                for item in data_list:
                    combination_data = item['combination']
                    movie_to_prefer_data = item['movie_to_prefer_key']

                    combination = Movie(combination_data['name'], combination_data['year'])
                    mapping.append(AutoSelection(combination, movie_to_prefer_data))

                return mapping

    @staticmethod
    def store_json(items):
        serialized_data = json.dumps([i.to_json() for i in items], indent=3)
        with open(config.autoselection_path, 'w') as file:
            file.write(serialized_data)
