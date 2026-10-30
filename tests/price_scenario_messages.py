"""Report completed scenario fragments from real Streamlit WebSocket traffic."""
import base64
import json
import sys

from streamlit.proto.ForwardMsg_pb2 import ForwardMsg

scenario_ids = set()
active = False
for line in sys.stdin:
    msg = ForwardMsg()
    msg.ParseFromString(base64.b64decode(line))
    kind = msg.WhichOneof("type")
    if kind == "delta" and "What if SOXL were this price?" in str(msg.delta):
        if msg.delta.fragment_id:
            scenario_ids.add(msg.delta.fragment_id)
    elif kind == "new_session":
        active = bool(scenario_ids.intersection(msg.new_session.fragment_ids_this_run))
    elif kind == "script_finished":
        if active and msg.script_finished == ForwardMsg.FINISHED_FRAGMENT_RUN_SUCCESSFULLY:
            print(json.dumps({"scenarioFinished": True}), flush=True)
        active = False
