"""Decode real Streamlit traffic; do not mistake a timer for a fragment run."""
import base64
import json
import sys
from streamlit.proto.ForwardMsg_pb2 import ForwardMsg

chart_fragments = set()
running = False
for line in sys.stdin:
    message = ForwardMsg()
    message.ParseFromString(base64.b64decode(line))
    kind = message.WhichOneof("type")
    if kind == "delta" and "soxl:market-update" in str(message.delta):
        if message.delta.fragment_id:
            chart_fragments.add(message.delta.fragment_id)
    if kind == "new_session":
        running = bool(chart_fragments.intersection(
            message.new_session.fragment_ids_this_run))
    if kind == "script_finished" and running:
        if message.script_finished == ForwardMsg.FINISHED_FRAGMENT_RUN_SUCCESSFULLY:
            print(json.dumps({"chartFragmentFinished": True}), flush=True)
        running = False
