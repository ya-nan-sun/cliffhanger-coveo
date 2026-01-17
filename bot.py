import random
from game_message import *


class Bot:
    def __init__(self):
        print("Initializing nutrient-hungry bot")
        random.seed()

    def _manhattan(self, a: Position, b: Position) -> int:
        return abs(a.x - b.x) + abs(a.y - b.y)

    def _nearest_target(self, start: Position, candidates: list[Position]) -> Position | None:
        if not candidates:
            return None
        best = min(candidates, key=lambda p: abs(p.x - start.x) + abs(p.y - start.y))
        return best

    def get_next_move(self, game_message: TeamGameState) -> list[Action]:
        # New behavior: find tiles with nutrients (map.nutrientGrid>0) and assign spores to claim them.
        actions: list[Action] = []

        world = game_message.world
        my_team: TeamInfo = world.teamInfos[game_message.yourTeamId]

        used_spore_ids: set[str] = set()
        used_spawner_ids: set[str] = set()

        # Debug: print current spores (id, position, biomass) for easier tracing
        try:
            spores_info = ", ".join(
                f"{s.id}@({s.position.x},{s.position.y})=b{s.biomass}" for s in my_team.spores
            ) if my_team.spores else "(no spores)"
            print(f"Team {my_team.teamId} spores: {spores_info}")
        except Exception:
            pass

        width = world.map.width
        height = world.map.height

        # collect nutrient tiles that are not owned by us
        nutrient_tiles: list[Position] = []
        for y in range(height):
            for x in range(width):
                nut = world.map.nutrientGrid[y][x]
                owner = world.ownershipGrid[y][x]
                if nut > 0 and owner != my_team.teamId:
                    nutrient_tiles.append(Position(x=x, y=y))

        # Debug: show a few nutrient targets we will consider (should be non-owned)
        try:
            if nutrient_tiles:
                sample = nutrient_tiles[:10]
                detail = ", ".join(f"({p.x},{p.y})={world.map.nutrientGrid[p.y][p.x]}" for p in sample)
                print(f"Found {len(nutrient_tiles)} nutrient tiles (non-owned). Sample: {detail}")
            else:
                print("No non-owned nutrient tiles found this tick.")
        except Exception:
            pass

    # Spawner creation from spores is deferred here: to ensure every spore can move each tick,
    # we prioritize issuing movement (or split) actions for all spores. Spawner creation can
    # still occur via other mechanisms or future ticks when a spore is intentionally left idle.

        # Produce spores from spawners using up to 20% of current team nutrients per spawner
        # Interpretation: allocate up to 20% of `my_team.nutrients` for each spawner, but cap total spending to available nutrients.
        # Prefer spawners that are close to high-nutrient unowned tiles or low-biomass foreign tiles (easy captures).
        # Produce spores using 20% of available nutrients each tick (total across all spawners)
        total_nutrients = my_team.nutrients
        to_spend = max(0, int(total_nutrients * 0.2))
        if to_spend > 0 and my_team.spawners:
            # identify high-value nutrient targets and low-biomass foreign tiles for prioritization
            high_nutrient_targets = [p for p in nutrient_tiles]
            low_biom_targets = []
            for y in range(height):
                for x in range(width):
                    owner = world.ownershipGrid[y][x]
                    if owner != my_team.teamId:
                        b = world.biomassGrid[y][x]
                        if b <= 2:
                            low_biom_targets.append(Position(x=x, y=y))

            def spawner_score(sp: Spawner) -> int:
                best = 10_000_000
                for p in high_nutrient_targets:
                    d = self._manhattan(sp.position, p)
                    if d < best:
                        best = d
                for p in low_biom_targets:
                    d = self._manhattan(sp.position, p)
                    if d < best:
                        best = d
                if best == 10_000_000:
                    return 999999
                return best

            spawners_sorted = sorted(my_team.spawners, key=spawner_score)
            # distribute to_spend evenly across prioritized spawners
            n = len(spawners_sorted)
            if n > 0:
                base = to_spend // n
                extra = to_spend % n
                for i, sp in enumerate(spawners_sorted):
                    if to_spend <= 0:
                        break
                    if sp.id in used_spawner_ids:
                        continue
                    if spawner_score(sp) >= 999999:
                        continue
                    amt = base + (1 if i < extra else 0)
                    if amt <= 0:
                        continue
                    # ensure we don't exceed remaining budget
                    amt = min(amt, to_spend)
                    actions.append(SpawnerProduceSporeAction(spawnerId=sp.id, biomass=amt))
                    used_spawner_ids.add(sp.id)
                    to_spend -= amt

        # if no nutrient tiles, fallback to moving toward any non-owned tile
        non_owned_tiles: list[Position] = []
        for y in range(height):
            for x in range(width):
                owner = world.ownershipGrid[y][x]
                if owner != my_team.teamId:
                    non_owned_tiles.append(Position(x=x, y=y))

        # mobile spores: include every spore so we move each one every tick
        mobile_spores = list(my_team.spores)
        if not mobile_spores:
            return actions

        # Assign each mobile spore to a unique target tile (prefer nutrient tiles)
        assigned: set[tuple[int, int]] = set()

        def cardinal_step_towards(src: Position, dst: Position) -> Position:
            dx = dst.x - src.x
            dy = dst.y - src.y
            if abs(dx) >= abs(dy) and dx != 0:
                step = Position(x=src.x + (1 if dx > 0 else -1), y=src.y)
            elif dy != 0:
                step = Position(x=src.x, y=src.y + (1 if dy > 0 else -1))
            else:
                step = Position(x=src.x, y=src.y)
            return step

        # Merge logic: for every spore with biomass <= 2, pathfind (preferring our owned tiles)
        # toward the nearest friendly spore so they can merge. Reserve target tiles to avoid collisions.
        small_spores = [s for s in my_team.spores if s.biomass <= 2]

        def bfs_next_step_via_owned(start: Position, goal: Position) -> Position | None:
            # BFS that only traverses tiles owned by us (except the goal which may be unowned)
            from collections import deque

            start_coord = (start.x, start.y)
            goal_coord = (goal.x, goal.y)
            q = deque()
            q.append(start_coord)
            parent: dict[tuple[int, int], tuple[int, int] | None] = {start_coord: None}
            max_nodes = 2000
            nodes = 0
            while q and nodes < max_nodes:
                nodes += 1
                cx, cy = q.popleft()
                if (cx, cy) == goal_coord:
                    break
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = cx + dx, cy + dy
                    if not (0 <= nx < width and 0 <= ny < height):
                        continue
                    coord = (nx, ny)
                    if coord in parent:
                        continue
                    # can traverse if tile is owned by us, or it's the goal tile
                    try:
                        owned = world.ownershipGrid[ny][nx] == my_team.teamId
                    except Exception:
                        owned = False
                    if not owned and coord != goal_coord:
                        continue
                    parent[coord] = (cx, cy)
                    q.append(coord)

            # if goal not reached, return None
            if goal_coord not in parent:
                return None

            # reconstruct path to get the first step
            cur = goal_coord
            path = []
            while cur is not None:
                path.append(cur)
                cur = parent[cur]
            path.reverse()
            # path[0] == start_coord
            if len(path) < 2:
                return None
            nx, ny = path[1]
            return Position(x=nx, y=ny)

        for s in small_spores:
            if s.id in used_spore_ids:
                continue
            # find nearest other spore (any biomass)
            candidates = [o for o in my_team.spores if o.id != s.id]
            if not candidates:
                break
            nearest = min(candidates, key=lambda o: self._manhattan(s.position, o.position))

            # try BFS path that goes through our owned tiles
            next_pos = bfs_next_step_via_owned(s.position, nearest.position)
            if next_pos is None:
                # fallback: greedy cardinal step toward target, preferring owned neighbors
                best_step = None
                best_pref = -1
                sx, sy = s.position.x, s.position.y
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = sx + dx, sy + dy
                    if not (0 <= nx < width and 0 <= ny < height):
                        continue
                    if (nx, ny) in assigned:
                        continue
                    d_before = abs(sx - nearest.position.x) + abs(sy - nearest.position.y)
                    d_after = abs(nx - nearest.position.x) + abs(ny - nearest.position.y)
                    if d_after >= d_before:
                        continue
                    pref = 1 if world.ownershipGrid[ny][nx] == my_team.teamId else 0
                    if pref > best_pref:
                        best_pref = pref
                        best_step = Position(x=nx, y=ny)

                if best_step is None:
                    continue
                direction = Position(x=best_step.x - s.position.x, y=best_step.y - s.position.y)
                actions.append(SporeMoveAction(sporeId=s.id, direction=direction))
                used_spore_ids.add(s.id)
                assigned.add((best_step.x, best_step.y))
            else:
                # next_pos is absolute next tile; convert to direction
                if (next_pos.x, next_pos.y) in assigned or (next_pos.x == s.position.x and next_pos.y == s.position.y):
                    continue
                direction = Position(x=next_pos.x - s.position.x, y=next_pos.y - s.position.y)
                actions.append(SporeMoveAction(sporeId=s.id, direction=direction))
                used_spore_ids.add(s.id)
                assigned.add((next_pos.x, next_pos.y))

        # Work with copies so we can pop assigned targets
        nutrient_targets = list(nutrient_tiles)
        # sort nutrient targets by nutrient value descending to prioritise high-value tiles
        nutrient_targets.sort(key=lambda p: world.map.nutrientGrid[p.y][p.x], reverse=True)

        remaining_spores = sorted(mobile_spores, key=lambda s: s.biomass, reverse=True)

        # Split spores into two roles: hunters (top half by biomass) and spreaders (bottom half)
        n = len(remaining_spores)
        hunters_count = n // 2
        hunters = remaining_spores[:hunters_count]
        spreaders = remaining_spores[hunters_count:]

        # Helper: pick nearest nutrient target for a spore (unassigned)
        def pick_nearest_nutrient(spore: Spore) -> Position | None:
            best = None
            best_d = 10_000_000
            for t in nutrient_targets:
                coord = (t.x, t.y)
                if coord in assigned:
                    continue
                d = self._manhattan(spore.position, t)
                if d < best_d:
                    best_d = d
                    best = t
            return best

        # First: hunters — target nutrient tiles and create spawners when standing on them
        for spore in hunters:
            if spore.id in used_spore_ids:
                continue

            # if standing on an unowned nutrient tile and can afford spawner, create it (hunter dedicates action)
            px, py = spore.position.x, spore.position.y
            if world.map.nutrientGrid[py][px] > 0 and world.ownershipGrid[py][px] != my_team.teamId:
                if spore.biomass >= my_team.nextSpawnerCost:
                    actions.append(SporeCreateSpawnerAction(sporeId=spore.id))
                    used_spore_ids.add(spore.id)
                    assigned.add((px, py))
                    # remove from nutrient_targets if present
                    try:
                        nutrient_targets = [t for t in nutrient_targets if not (t.x == px and t.y == py)]
                    except Exception:
                        pass
                    continue

            # otherwise move toward nearest nutrient target if any
            target = pick_nearest_nutrient(spore)
            if target is None:
                # fall back to nearest non-owned tile
                best_idx = None
                best_dist = 10_000_000
                for i, p in enumerate(non_owned_tiles):
                    coord = (p.x, p.y)
                    if coord in assigned:
                        continue
                    d = self._manhattan(spore.position, p)
                    if d < best_dist:
                        best_dist = d
                        best_idx = i
                if best_idx is not None:
                    target = non_owned_tiles.pop(best_idx)
                else:
                    # random unassigned tile
                    attempts = 0
                    while attempts < 20:
                        tx = random.randint(0, width - 1)
                        ty = random.randint(0, height - 1)
                        if (tx, ty) not in assigned:
                            target = Position(x=tx, y=ty)
                            break
                        attempts += 1
                    else:
                        target = Position(x=random.randint(0, width - 1), y=random.randint(0, height - 1))

            # move or split to target
            dest_owner = world.ownershipGrid[target.y][target.x]
            dest_biomass = world.biomassGrid[target.y][target.x]
            is_own_trail = dest_owner == my_team.teamId and dest_biomass > 0
            will_cost = 0 if is_own_trail else 1
            if will_cost == 1 and spore.biomass - will_cost <= 1 and spore.biomass >= 3:
                biomass_for_mover = max(2, spore.biomass // 2)
                step = cardinal_step_towards(spore.position, target)
                actions.append(
                    SporeSplitAction(
                        sporeId=spore.id,
                        biomassForMovingSpore=biomass_for_mover,
                        direction=Position(x=step.x - spore.position.x, y=step.y - spore.position.y),
                    )
                )
                used_spore_ids.add(spore.id)
                assigned.add((target.x, target.y))
            else:
                # move one cardinal step toward the target
                step = cardinal_step_towards(spore.position, target)
                direction = Position(x=step.x - spore.position.x, y=step.y - spore.position.y)
                actions.append(SporeMoveAction(sporeId=spore.id, direction=direction))
                used_spore_ids.add(spore.id)
                assigned.add((target.x, target.y))

            # remove assigned nutrient target if applicable
            try:
                nutrient_targets = [t for t in nutrient_targets if (t.x, t.y) not in assigned]
            except Exception:
                pass

        # Second: spreaders — try to cover the map by moving to unique non-owned tiles
        other_targets = [p for p in non_owned_tiles if (p.x, p.y) not in assigned]
        for spore in spreaders:
            if spore.id in used_spore_ids:
                continue
            # pick nearest other target
            best_idx = None
            best_dist = 10_000_000
            for i, p in enumerate(other_targets):
                d = self._manhattan(spore.position, p)
                if d < best_dist:
                    best_dist = d
                    best_idx = i
            if best_idx is not None:
                target = other_targets.pop(best_idx)
                assigned.add((target.x, target.y))
                dest_owner = world.ownershipGrid[target.y][target.x]
                dest_biomass = world.biomassGrid[target.y][target.x]
                is_own_trail = dest_owner == my_team.teamId and dest_biomass > 0
                will_cost = 0 if is_own_trail else 1
                if will_cost == 1 and spore.biomass - will_cost <= 1 and spore.biomass >= 3:
                    biomass_for_mover = max(2, spore.biomass // 2)
                    step = cardinal_step_towards(spore.position, target)
                    actions.append(
                        SporeSplitAction(
                            sporeId=spore.id,
                            biomassForMovingSpore=biomass_for_mover,
                            direction=Position(x=step.x - spore.position.x, y=step.y - spore.position.y),
                        )
                    )
                    used_spore_ids.add(spore.id)
                else:
                    # move one cardinal step toward the target
                    step = cardinal_step_towards(spore.position, target)
                    direction = Position(x=step.x - spore.position.x, y=step.y - spore.position.y)
                    actions.append(SporeMoveAction(sporeId=spore.id, direction=direction))
                    used_spore_ids.add(spore.id)
            else:
                # no candidate targets left; pick a random unassigned tile
                attempts = 0
                while attempts < 20:
                    tx = random.randint(0, width - 1)
                    ty = random.randint(0, height - 1)
                    if (tx, ty) not in assigned:
                        target = Position(x=tx, y=ty)
                        break
                    attempts += 1
                else:
                    target = Position(x=random.randint(0, width - 1), y=random.randint(0, height - 1))
                # move one cardinal step toward the target
                step = cardinal_step_towards(spore.position, target)
                direction = Position(x=step.x - spore.position.x, y=step.y - spore.position.y)
                actions.append(SporeMoveAction(sporeId=spore.id, direction=direction))
                used_spore_ids.add(spore.id)
                assigned.add((target.x, target.y))

        # Ensure any spore not yet given an action this tick still moves.
        # In particular, don't leave spores stationary on spawners (they'll keep merging).
        try:
            spawner_coords = {(sp.position.x, sp.position.y) for sp in world.spawners}
        except Exception:
            spawner_coords = set()

        for s in my_team.spores:
            if s.id in used_spore_ids:
                continue
            # If spore stands on a spawner, move it off to avoid repeated merging
            px, py = s.position.x, s.position.y
            moved = False
            if (px, py) in spawner_coords:
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = px + dx, py + dy
                    if 0 <= nx < width and 0 <= ny < height and (nx, ny) not in assigned:
                        # prefer tiles that are not spawner tiles
                        if (nx, ny) not in spawner_coords:
                            actions.append(SporeMoveAction(sporeId=s.id, direction=Position(x=dx, y=dy)))
                            used_spore_ids.add(s.id)
                            assigned.add((nx, ny))
                            moved = True
                            break
                if not moved:
                    # no non-spawner adjacent free tile, pick any adjacent free tile
                    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        nx, ny = px + dx, py + dy
                        if 0 <= nx < width and 0 <= ny < height and (nx, ny) not in assigned:
                            actions.append(SporeMoveAction(sporeId=s.id, direction=Position(x=dx, y=dy)))
                            used_spore_ids.add(s.id)
                            assigned.add((nx, ny))
                            moved = True
                            break
                if moved:
                    continue

            # otherwise, move toward nearest unassigned non-owned tile (to expand)
            best = None
            best_d = 10_000_000
            for p in non_owned_tiles:
                coord = (p.x, p.y)
                if coord in assigned:
                    continue
                d = self._manhattan(s.position, p)
                if d < best_d:
                    best_d = d
                    best = p
            if best is not None:
                step = cardinal_step_towards(s.position, best)
                direction = Position(x=step.x - s.position.x, y=step.y - s.position.y)
                nx, ny = s.position.x + direction.x, s.position.y + direction.y
                if 0 <= nx < width and 0 <= ny < height and (nx, ny) not in assigned:
                    actions.append(SporeMoveAction(sporeId=s.id, direction=direction))
                    used_spore_ids.add(s.id)
                    assigned.add((nx, ny))
                    continue

            # final fallback: move randomly one tile to ensure activity
            attempts = 0
            while attempts < 10:
                dx, dy = random.choice(((1, 0), (-1, 0), (0, 1), (0, -1)))
                nx, ny = px + dx, py + dy
                if 0 <= nx < width and 0 <= ny < height and (nx, ny) not in assigned:
                    actions.append(SporeMoveAction(sporeId=s.id, direction=Position(x=dx, y=dy)))
                    used_spore_ids.add(s.id)
                    assigned.add((nx, ny))
                    break
                attempts += 1

        # Debug
        try:
            print(f"Tick {game_message.tick}: scheduled {len(actions)} actions to nutrient tiles={len(nutrient_tiles)}")
            for a in actions:
                if isinstance(a, SporeMoveAction):
                    print(f"  SporeMove spore={a.sporeId} dir=({a.direction.x},{a.direction.y})")
        except Exception:
            pass

        return actions
