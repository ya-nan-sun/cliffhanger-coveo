from gettext import find
import random
from game_message import *


class Bot:
    def __init__(self):
        print("Initializing your super mega duper bot")
    
    def find_highest_tile(self, game_message, nutrient_grid: list[list[int]]) -> tuple[int]:
        max_nutrient = -1
        max_position = (0, 0)
        for y in range(len(nutrient_grid)):
            for x in range(len(nutrient_grid[0])):
                if game_message.world.ownershipGrid[x][y] == game_message.yourTeamId:
                    continue
                if nutrient_grid[y][x] > max_nutrient:
                    max_nutrient = nutrient_grid[y][x]
                    max_position = (x, y)
        return max_position

    def get_next_move(self, game_message: TeamGameState) -> list[Action]:
        """
        Here is where the magic happens, for now the moves are not very good. I bet you can do better ;)
        """
        actions = []

        my_team: TeamInfo = game_message.world.teamInfos[game_message.yourTeamId]
        if len(my_team.spawners) == 0:
            actions.append(SporeCreateSpawnerAction(sporeId=my_team.spores[0].id))

        elif len(my_team.spores) == 0:
            actions.append(
                SpawnerProduceSporeAction(spawnerId=my_team.spawners[0].id, biomass=20)
            )
        if my_team.nutrients >= 10:
            actions.append(
                SpawnerProduceSporeAction(spawnerId=my_team.spawners[0].id, biomass=10)
            )
        x = self.find_highest_tile(game_message,game_message.world.map.nutrientGrid)[0]
        y = self.find_highest_tile(game_message,game_message.world.map.nutrientGrid)[1]


        for spore in my_team.spores:
            actions.append(
            SporeMoveToAction(
                sporeId=spore.id,
                position=Position(
                    x=x,
                    y=y,
                ),
            )
        )





        # You can clearly do better than the random actions above. Have fun!!
        return actions
