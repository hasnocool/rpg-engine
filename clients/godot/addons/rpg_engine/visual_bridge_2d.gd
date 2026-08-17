extends Node2D
class_name RPGVisualBridge2D

signal scene_requested(scene_path: String)

@export var pixels_per_unit: float = 32.0
var _actors: Dictionary = {}

func apply_snapshot(snapshot: Dictionary) -> void:
    var scene_path := str(snapshot.get("scene_2d", ""))
    if not scene_path.is_empty():
        scene_requested.emit(scene_path)

    var seen: Dictionary = {}
    for actor in snapshot.get("actors", []):
        var actor_id := str(actor.get("entity_id", ""))
        if actor_id.is_empty():
            continue
        seen[actor_id] = true
        var node := _actors.get(actor_id) as Node2D
        if node == null:
            node = _spawn_actor(actor)
            _actors[actor_id] = node
        node.position = Vector2(
            float(actor.get("x", 0.0)) * pixels_per_unit,
            float(actor.get("y", 0.0)) * pixels_per_unit,
        )

    for actor_id in _actors.keys():
        if not seen.has(actor_id):
            var stale := _actors[actor_id] as Node2D
            if is_instance_valid(stale):
                stale.queue_free()
            _actors.erase(actor_id)

func apply_presentation(envelope: Dictionary) -> void:
    for batch in envelope.get("batches", []):
        for hint in batch.get("hints", []):
            _apply_hint(hint)

func _spawn_actor(actor: Dictionary) -> Node2D:
    var scene_path := str(actor.get("scene_2d", ""))
    if not scene_path.is_empty():
        var packed = load(scene_path)
        if packed is PackedScene:
            var instance = packed.instantiate()
            if instance is Node2D:
                add_child(instance)
                return instance
    var fallback := Node2D.new()
    var label := Label.new()
    label.text = str(actor.get("terminal_glyph", "?"))
    fallback.add_child(label)
    add_child(fallback)
    return fallback

func _apply_hint(hint: Dictionary) -> void:
    var actor_id := str(hint.get("entity_id", ""))
    var node := _actors.get(actor_id) as Node2D
    match str(hint.get("type", "")):
        "movement_interpolation":
            if node == null:
                return
            var target: Dictionary = hint.get("to_position", {})
            var target_position := Vector2(
                float(target.get("x", 0.0)) * pixels_per_unit,
                float(target.get("y", 0.0)) * pixels_per_unit,
            )
            var duration := float(hint.get("duration_ms", 250)) / 1000.0
            create_tween().set_trans(Tween.TRANS_QUAD).set_ease(Tween.EASE_IN_OUT).tween_property(
                node, "position", target_position, duration
            )
        "animation":
            _play_animation(node, str(hint.get("animation", "")))
        "vfx":
            _spawn_vfx(node, str(hint.get("resource_2d", "")))
        "audio":
            _play_audio(node, str(hint.get("resource", "")))

func _play_animation(node: Node2D, animation: String) -> void:
    if node == null or animation.is_empty():
        return
    var player := node.get_node_or_null("AnimationPlayer") as AnimationPlayer
    if player != null and player.has_animation(animation):
        player.play(animation)

func _spawn_vfx(node: Node2D, resource_path: String) -> void:
    if resource_path.is_empty():
        return
    var packed = load(resource_path)
    if packed is PackedScene:
        var effect = packed.instantiate()
        if effect is Node2D:
            add_child(effect)
            effect.position = node.position if node != null else Vector2.ZERO

func _play_audio(node: Node2D, resource_path: String) -> void:
    if resource_path.is_empty():
        return
    var stream = load(resource_path)
    if stream is AudioStream:
        var player := AudioStreamPlayer2D.new()
        player.stream = stream
        add_child(player)
        player.position = node.position if node != null else Vector2.ZERO
        player.finished.connect(player.queue_free)
        player.play()
