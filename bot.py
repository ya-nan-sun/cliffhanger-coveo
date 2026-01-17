from gettext import find
import random
from game_message import *


class Bot:
    def __init__(self):
        print("Initializing your super mega duper bot")
    
    def find_highest_tile(self,spore, game_message, nutrient_grid: list[list[int]]) -> tuple[int]:
        max_nutrient = -1
        min_position = (0, 0)
        min_distance = 10000000000

        for x in range(len(nutrient_grid)):
            for y in range(len(nutrient_grid[0])):
                if game_message.world.ownershipGrid[x][y] == game_message.yourTeamId or nutrient_grid[x][y] == 0:
                    continue
                distance = abs(spore.position.x - x) + abs(spore.position.y - y)
                if distance < min_distance and distance > 0:
                    min_distance = distance
                    min_position = (x, y)
            
        return min_position

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
            return actions
        elif len(my_team.spores) >= 10:
            actions.append(
                SpawnerProduceSporeAction(spawnerId=my_team.spawners[0].id, biomass= 50)
            )
        elif my_team.nutrients >= 10:
            actions.append(
                SpawnerProduceSporeAction(spawnerId=my_team.spawners[0].id, biomass= int(0.5*my_team.nutrients))
            )


        for spore in my_team.spores:
            actions.append(
            SporeMoveToAction(
                sporeId=spore.id,
                position=Position(
                    x=self.find_highest_tile(spore, game_message,game_message.world.map.nutrientGrid)[0],
                    y=self.find_highest_tile(spore, game_message,game_message.world.map.nutrientGrid)[1],
                ),
            )
        )





        # You can clearly do better than the random actions above. Have fun!!
        return actions
