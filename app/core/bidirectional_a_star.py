# app/core/bidirectional_a_star.py

from __future__ import annotations

import heapq
import time
from dataclasses import dataclass
from math import inf
from typing import Any, Iterable

import networkx as nx

from app.core.a_star import haversine_m


@dataclass(frozen=True)
class BidirectionalAStarResult:
    path: list[Any]
    distance_m: float
    nodes_expanded: int
    route_time_ms: float
    meeting_node: Any | None
    forward_nodes_expanded: int
    backward_nodes_expanded: int


def bidirectional_astar_shortest_path(
    graph: nx.Graph,
    start: Any,
    goal: Any,
) -> BidirectionalAStarResult:
    """
    Optimized Bidirectional A*.

    NetworkX is used only as the graph container.
    This function does not call nx.shortest_path(), nx.astar_path(),
    or nx.dijkstra_path().

    Directed graph behavior:
    - forward search follows successors
    - backward search follows predecessors

    Optimization:
    - caches node coordinates
    - caches heuristic-to-start and heuristic-to-goal values
    - caches edge lengths
    - avoids converting successors/predecessors to lists
    """
    started_at = time.perf_counter()

    if start not in graph:
        raise nx.NodeNotFound(f"Start node {start} not found in graph.")

    if goal not in graph:
        raise nx.NodeNotFound(f"Goal node {goal} not found in graph.")

    if start == goal:
        return BidirectionalAStarResult(
            path=[start],
            distance_m=0.0,
            nodes_expanded=0,
            route_time_ms=round((time.perf_counter() - started_at) * 1000, 3),
            meeting_node=start,
            forward_nodes_expanded=0,
            backward_nodes_expanded=0,
        )

    coordinate_cache: dict[Any, tuple[float, float] | None] = {}
    h_start_cache: dict[Any, float] = {}
    h_goal_cache: dict[Any, float] = {}
    edge_length_cache: dict[tuple[Any, Any], float] = {}

    def coord(node: Any) -> tuple[float, float] | None:
        if node in coordinate_cache:
            return coordinate_cache[node]

        node_data = graph.nodes[node]
        lat = node_data.get("y")
        lon = node_data.get("x")

        if lat is None or lon is None:
            coordinate_cache[node] = None
            return None

        value = (float(lat), float(lon))
        coordinate_cache[node] = value
        return value

    start_coord = coord(start)
    goal_coord = coord(goal)

    def h_to_start(node: Any) -> float:
        if node in h_start_cache:
            return h_start_cache[node]

        node_coord = coord(node)

        if node_coord is None or start_coord is None:
            h_start_cache[node] = 0.0
            return 0.0

        value = haversine_m(
            node_coord[0],
            node_coord[1],
            start_coord[0],
            start_coord[1],
        )
        h_start_cache[node] = value
        return value

    def h_to_goal(node: Any) -> float:
        if node in h_goal_cache:
            return h_goal_cache[node]

        node_coord = coord(node)

        if node_coord is None or goal_coord is None:
            h_goal_cache[node] = 0.0
            return 0.0

        value = haversine_m(
            node_coord[0],
            node_coord[1],
            goal_coord[0],
            goal_coord[1],
        )
        h_goal_cache[node] = value
        return value

    def forward_potential(node: Any) -> float:
        return (h_to_goal(node) - h_to_start(node)) / 2.0

    def backward_potential(node: Any) -> float:
        return (h_to_start(node) - h_to_goal(node)) / 2.0

    def fallback_edge_length_m(u: Any, v: Any) -> float:
        u_coord = coord(u)
        v_coord = coord(v)

        if u_coord is None or v_coord is None:
            return 1.0

        return haversine_m(
            u_coord[0],
            u_coord[1],
            v_coord[0],
            v_coord[1],
        )

    def edge_length_m(u: Any, v: Any) -> float:
        cache_key = (u, v)

        if cache_key in edge_length_cache:
            return edge_length_cache[cache_key]

        edge_data = graph.get_edge_data(u, v)

        if edge_data is None:
            raise nx.NetworkXNoPath(f"No edge found between {u} and {v}")

        lengths: list[float] = []

        if graph.is_multigraph():
            for data in edge_data.values():
                if isinstance(data, dict) and data.get("length") is not None:
                    lengths.append(float(data["length"]))
        else:
            if isinstance(edge_data, dict) and edge_data.get("length") is not None:
                lengths.append(float(edge_data["length"]))

        if lengths:
            value = min(lengths)
        else:
            value = fallback_edge_length_m(u, v)

        edge_length_cache[cache_key] = value
        return value

    def successors(node: Any) -> Iterable[Any]:
        if graph.is_directed():
            return graph.successors(node)

        return graph.neighbors(node)

    def predecessors(node: Any) -> Iterable[Any]:
        if graph.is_directed():
            return graph.predecessors(node)

        return graph.neighbors(node)

    def push_forward(
        heap: list[tuple[float, int, Any]],
        counter: int,
        node: Any,
        g_score: dict[Any, float],
    ) -> int:
        priority = g_score[node] + forward_potential(node)
        heapq.heappush(heap, (priority, counter, node))
        return counter + 1

    def push_backward(
        heap: list[tuple[float, int, Any]],
        counter: int,
        node: Any,
        g_score: dict[Any, float],
    ) -> int:
        priority = g_score[node] + backward_potential(node)
        heapq.heappush(heap, (priority, counter, node))
        return counter + 1

    def peek_valid_priority(
        heap: list[tuple[float, int, Any]],
        closed: set[Any],
    ) -> float:
        while heap and heap[0][2] in closed:
            heapq.heappop(heap)

        if not heap:
            return inf

        return heap[0][0]

    def reconstruct_path(
        meeting_node: Any,
        came_from_forward: dict[Any, Any],
        came_from_backward: dict[Any, Any],
    ) -> list[Any]:
        forward_path = [meeting_node]
        current = meeting_node

        while current != start:
            current = came_from_forward[current]
            forward_path.append(current)

        forward_path.reverse()

        backward_path = []
        current = meeting_node

        while current != goal:
            current = came_from_backward[current]
            backward_path.append(current)

        return forward_path + backward_path

    def path_distance_m(path: list[Any]) -> float:
        if len(path) <= 1:
            return 0.0

        total = 0.0

        for u, v in zip(path, path[1:]):
            total += edge_length_m(u, v)

        return total

    forward_heap: list[tuple[float, int, Any]] = []
    backward_heap: list[tuple[float, int, Any]] = []

    forward_counter = 0
    backward_counter = 0

    forward_g: dict[Any, float] = {start: 0.0}
    backward_g: dict[Any, float] = {goal: 0.0}

    came_from_forward: dict[Any, Any] = {}
    came_from_backward: dict[Any, Any] = {}

    forward_closed: set[Any] = set()
    backward_closed: set[Any] = set()

    forward_counter = push_forward(
        forward_heap,
        forward_counter,
        start,
        forward_g,
    )

    backward_counter = push_backward(
        backward_heap,
        backward_counter,
        goal,
        backward_g,
    )

    best_distance = inf
    meeting_node: Any | None = None

    forward_expanded = 0
    backward_expanded = 0

    while forward_heap and backward_heap:
        forward_min_priority = peek_valid_priority(forward_heap, forward_closed)
        backward_min_priority = peek_valid_priority(backward_heap, backward_closed)

        if forward_min_priority == inf or backward_min_priority == inf:
            break

        if meeting_node is not None and (
            forward_min_priority + backward_min_priority >= best_distance
        ):
            break

        expand_forward = forward_min_priority <= backward_min_priority

        if expand_forward:
            _, _, current = heapq.heappop(forward_heap)

            if current in forward_closed:
                continue

            forward_closed.add(current)
            forward_expanded += 1

            if current in backward_g:
                candidate_distance = forward_g[current] + backward_g[current]

                if candidate_distance < best_distance:
                    best_distance = candidate_distance
                    meeting_node = current

            for neighbor in successors(current):
                tentative_g = forward_g[current] + edge_length_m(current, neighbor)

                if tentative_g >= forward_g.get(neighbor, inf):
                    continue

                forward_g[neighbor] = tentative_g
                came_from_forward[neighbor] = current

                if neighbor in backward_g:
                    candidate_distance = tentative_g + backward_g[neighbor]

                    if candidate_distance < best_distance:
                        best_distance = candidate_distance
                        meeting_node = neighbor

                forward_counter = push_forward(
                    forward_heap,
                    forward_counter,
                    neighbor,
                    forward_g,
                )

        else:
            _, _, current = heapq.heappop(backward_heap)

            if current in backward_closed:
                continue

            backward_closed.add(current)
            backward_expanded += 1

            if current in forward_g:
                candidate_distance = forward_g[current] + backward_g[current]

                if candidate_distance < best_distance:
                    best_distance = candidate_distance
                    meeting_node = current

            for neighbor in predecessors(current):
                tentative_g = backward_g[current] + edge_length_m(neighbor, current)

                if tentative_g >= backward_g.get(neighbor, inf):
                    continue

                backward_g[neighbor] = tentative_g
                came_from_backward[neighbor] = current

                if neighbor in forward_g:
                    candidate_distance = forward_g[neighbor] + tentative_g

                    if candidate_distance < best_distance:
                        best_distance = candidate_distance
                        meeting_node = neighbor

                backward_counter = push_backward(
                    backward_heap,
                    backward_counter,
                    neighbor,
                    backward_g,
                )

    if meeting_node is None:
        raise nx.NetworkXNoPath(f"No path found between {start} and {goal}")

    path = reconstruct_path(
        meeting_node=meeting_node,
        came_from_forward=came_from_forward,
        came_from_backward=came_from_backward,
    )

    distance_m = path_distance_m(path)
    route_time_ms = (time.perf_counter() - started_at) * 1000

    return BidirectionalAStarResult(
        path=path,
        distance_m=round(distance_m, 3),
        nodes_expanded=forward_expanded + backward_expanded,
        route_time_ms=round(route_time_ms, 3),
        meeting_node=meeting_node,
        forward_nodes_expanded=forward_expanded,
        backward_nodes_expanded=backward_expanded,
    )


def bidirectional_a_star_shortest_path(
    graph: nx.Graph,
    start: Any,
    goal: Any,
) -> BidirectionalAStarResult:
    return bidirectional_astar_shortest_path(graph, start, goal)