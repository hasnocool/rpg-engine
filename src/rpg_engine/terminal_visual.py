"""ASCII renderer for VisualSnapshot, shared by local terminal and SSH sessions."""

from __future__ import annotations

from rpg_engine.visuals import VisualSnapshot


def _put(canvas: list[list[str]], x: int, y: int, text: str) -> None:
    if not 0 <= y < len(canvas):
        return
    row = canvas[y]
    for offset, char in enumerate(text):
        target = x + offset
        if 0 <= target < len(row):
            row[target] = char


def _center_x(width: int, text: str) -> int:
    return max(0, (width - len(text)) // 2)


def render_visual_snapshot(snapshot: VisualSnapshot, *, width: int = 61, height: int = 17) -> str:
    """Render a deterministic logical scene without requiring terminal-specific game state."""

    width = max(41, width)
    height = max(13, height)
    canvas = [[" " for _ in range(width)] for _ in range(height)]
    center_x = width // 2
    center_y = height // 2
    location_name = (
        snapshot.terminal_title
        or snapshot.location_name
        or snapshot.location_id
        or "Unknown"
    )
    location = f"[{location_name}]"
    _put(canvas, _center_x(width, location), center_y, location)

    exit_slots = [
        (center_x, 1, "vertical"),
        (width - 2, center_y, "horizontal"),
        (center_x, height - 2, "vertical"),
        (1, center_y, "horizontal"),
    ]
    for index, exit_view in enumerate(sorted(snapshot.exits, key=lambda item: item.destination_id)):
        if index >= len(exit_slots):
            break
        x, y, orientation = exit_slots[index]
        label = f"[{exit_view.destination_name}]"
        if orientation == "vertical":
            _put(canvas, _center_x(width, label), y, label)
            step = 1 if y < center_y else -1
            for line_y in range(y + step, center_y, step):
                _put(canvas, center_x, line_y, "|")
        else:
            label_x = 0 if x < center_x else max(0, width - len(label))
            _put(canvas, label_x, y, label)
            start = len(label) if x < center_x else center_x + len(location) // 2 + 1
            end = center_x - len(location) // 2 if x < center_x else width - len(label)
            for line_x in range(min(start, end), max(start, end)):
                _put(canvas, line_x, y, "-")

    actors = sorted(snapshot.actors, key=lambda actor: actor.entity_id)
    for index, actor in enumerate(actors):
        if actor.logical_position.x is not None or actor.logical_position.y is not None:
            x = center_x + int(actor.x)
            y = center_y - 2 + int(actor.y)
        else:
            x = center_x - max(1, len(actors) // 2) + index * 2
            y = center_y - 2
        _put(canvas, x, y, actor.terminal_glyph[:1] or "?")

    rendered = ["".join(row).rstrip() for row in canvas]
    while rendered and not rendered[-1]:
        rendered.pop()
    legend = "  ".join(f"{actor.terminal_glyph[:1]}={actor.name}" for actor in actors)
    if len(snapshot.exits) > 4:
        extras = ", ".join(
            item.destination_name
            for item in sorted(snapshot.exits, key=lambda item: item.destination_id)[4:]
        )
        rendered.append(f"Other exits: {extras}")
    if legend:
        rendered.append(f"Actors: {legend}")
    rendered.append(f"sequence={snapshot.sequence} campaign={snapshot.campaign_id}")
    return "\n".join(rendered)
