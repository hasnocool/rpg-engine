extends Node
class_name RPGApiClient

signal visual_received(snapshot: Dictionary)
signal presentation_received(envelope: Dictionary)
signal command_completed(envelope: Dictionary)
signal request_failed(message: String)

@export var base_url: String = "http://127.0.0.1:8000"

var _visual_request: HTTPRequest
var _command_request: HTTPRequest
var _socket := WebSocketPeer.new()
var _socket_active := false

func _ready() -> void:
    _visual_request = HTTPRequest.new()
    _command_request = HTTPRequest.new()
    add_child(_visual_request)
    add_child(_command_request)
    _visual_request.request_completed.connect(_on_visual_request_completed)
    _command_request.request_completed.connect(_on_command_request_completed)

func request_visual(campaign_id: String, actor_id: String = "") -> Error:
    var url := "%s/api/v1/campaigns/%s/visual" % [base_url.rstrip("/"), campaign_id.uri_encode()]
    if not actor_id.is_empty():
        url += "?actor_id=" + actor_id.uri_encode()
    return _visual_request.request(url)

func send_command(campaign_id: String, command: Dictionary) -> Error:
    var url := "%s/api/v1/campaigns/%s/commands" % [
        base_url.rstrip("/"),
        campaign_id.uri_encode(),
    ]
    return _command_request.request(
        url,
        ["Content-Type: application/json"],
        HTTPClient.METHOD_POST,
        JSON.stringify(command),
    )

func connect_presentation(campaign_id: String, after_sequence: int = 0) -> Error:
    var ws_base := base_url.rstrip("/")
    if ws_base.begins_with("https://"):
        ws_base = "wss://" + ws_base.trim_prefix("https://")
    elif ws_base.begins_with("http://"):
        ws_base = "ws://" + ws_base.trim_prefix("http://")
    var url := "%s/api/v1/campaigns/%s/presentation/ws?after=%d" % [
        ws_base,
        campaign_id.uri_encode(),
        after_sequence,
    ]
    var result := _socket.connect_to_url(url)
    _socket_active = result == OK
    return result

func disconnect_presentation() -> void:
    if _socket_active:
        _socket.close()
    _socket_active = false

func _process(_delta: float) -> void:
    if not _socket_active:
        return
    _socket.poll()
    var state := _socket.get_ready_state()
    if state == WebSocketPeer.STATE_CLOSED:
        _socket_active = false
        return
    while _socket.get_available_packet_count() > 0:
        var text := _socket.get_packet().get_string_from_utf8()
        var payload = JSON.parse_string(text)
        if typeof(payload) == TYPE_DICTIONARY:
            presentation_received.emit(payload)

func _decode_response(body: PackedByteArray) -> Dictionary:
    var payload = JSON.parse_string(body.get_string_from_utf8())
    if typeof(payload) == TYPE_DICTIONARY:
        return payload
    return {}

func _on_visual_request_completed(
    _result: int,
    response_code: int,
    _headers: PackedStringArray,
    body: PackedByteArray,
) -> void:
    if response_code < 200 or response_code >= 300:
        request_failed.emit("visual request failed with HTTP %d" % response_code)
        return
    var payload := _decode_response(body)
    if payload.has("visual"):
        visual_received.emit(payload["visual"])

func _on_command_request_completed(
    _result: int,
    response_code: int,
    _headers: PackedStringArray,
    body: PackedByteArray,
) -> void:
    if response_code < 200 or response_code >= 300:
        request_failed.emit("command request failed with HTTP %d" % response_code)
        return
    command_completed.emit(_decode_response(body))
