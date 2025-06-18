import os
import struct
import socket
import json
from typing import Optional, Dict, Any
from fastapi import FastAPI, Request, Response, status, Query
from fastapi.responses import StreamingResponse, JSONResponse
import uvicorn

# Load configuration from environment variables
DEVICE_IP = os.environ.get('DEVICE_IP', '127.0.0.1')
DEVICE_UDP_PORT = int(os.environ.get('DEVICE_UDP_PORT', '10101'))
HTTP_SERVER_HOST = os.environ.get('HTTP_SERVER_HOST', '0.0.0.0')
HTTP_SERVER_PORT = int(os.environ.get('HTTP_SERVER_PORT', '8080'))
UDP_TIMEOUT = float(os.environ.get('DEVICE_UDP_TIMEOUT', '1.5'))

app = FastAPI(
    title="DEEP Robotics Lite3 Quadruped DeviceShifu",
    description="HTTP API for controlling and monitoring DEEP Robotics Lite3 Quadruped Robot",
    version="1.0"
)

# Protocol message format definitions (MUST be updated per actual SDK/protocol)
# These are EXAMPLES; adapt as per real device docs.
COMMAND_HEADER = b'\xA5\x5A'  # Example header for commands (update as needed)
STATE_REQUEST = b'\xA5\x5A\x01\x00'  # Example state request command (update as needed)
SENSOR_REQUEST = b'\xA5\x5A\x02\x00'  # Example sensor request command (update as needed)

def send_udp_message(payload: bytes, expect_reply: bool = True, reply_size: int = 1024) -> Optional[bytes]:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(UDP_TIMEOUT)
        sock.sendto(payload, (DEVICE_IP, DEVICE_UDP_PORT))
        if not expect_reply:
            return None
        try:
            data, _ = sock.recvfrom(reply_size)
            return data
        except socket.timeout:
            return None

def parse_state(data: bytes) -> Dict[str, Any]:
    # Dummy unpack, real device: update struct format and field mapping
    # Example: <header(2), posture(1), joint_angles(12*4), joint_velocities(12*4), position(3*4), gait(1)>
    # For demo, let's assume:
    # header(2), posture(1), 12 floats joint_angles, 12 floats joint_velocities, 3 floats position, gait(1)
    try:
        if len(data) < 2 + 1 + 12*4 + 12*4 + 3*4 + 1:
            raise Exception("State packet too short")
        offset = 2  # skip header
        posture = struct.unpack_from('<B', data, offset)[0]
        offset += 1
        joint_angles = list(struct.unpack_from('<12f', data, offset))
        offset += 12*4
        joint_velocities = list(struct.unpack_from('<12f', data, offset))
        offset += 12*4
        position = list(struct.unpack_from('<3f', data, offset))
        offset += 3*4
        gait = struct.unpack_from('<B', data, offset)[0]
        return {
            "posture": posture,
            "joint_angles": joint_angles,
            "joint_velocities": joint_velocities,
            "position": position,
            "gait": gait
        }
    except Exception:
        return {"raw": data.hex()}

def parse_sensors(data: bytes) -> Dict[str, Any]:
    # Dummy unpack, real device: update struct format and field mapping
    # Example: <header(2), imu(9*4), battery(2*4), velocity(3*4)>
    try:
        if len(data) < 2 + 9*4 + 2*4 + 3*4:
            raise Exception("Sensor packet too short")
        offset = 2
        imu = list(struct.unpack_from('<9f', data, offset))  # 3-acc, 3-gyro, 3-mag
        offset += 9*4
        battery = list(struct.unpack_from('<2f', data, offset))  # voltage, level
        offset += 2*4
        velocity = list(struct.unpack_from('<3f', data, offset))  # vx, vy, vtheta
        return {
            "imu": {
                "acc": imu[0:3],
                "gyro": imu[3:6],
                "mag": imu[6:9],
            },
            "battery": {
                "voltage": battery[0],
                "level": battery[1],
            },
            "velocity": {
                "vx": velocity[0],
                "vy": velocity[1],
                "vtheta": velocity[2]
            }
        }
    except Exception:
        return {"raw": data.hex()}

@app.post("/command")
async def command(payload: Dict[str, Any]):
    """
    Submit various operational commands to the robot such as heartbeat, mode switch,
    axis (posture/movement) commands, gait change, or action commands (e.g., flip, backflip).
    The command should be specified in the JSON payload.
    """
    try:
        # Example: Expecting {"cmd": "heartbeat", "params": {...}}
        cmd = payload.get("cmd")
        params = payload.get("params", {})
        # Build binary command according to protocol
        # -- THIS IS AN EXAMPLE, you must adjust to the actual protocol --
        body = b''
        if cmd == "heartbeat":
            body = b'\x01'
        elif cmd == "state_change":
            mode = params.get("mode", 0)
            body = b'\x02' + struct.pack('<B', mode)
        elif cmd == "axis":
            # axis: posture/move; params: joint_id (0-11), angle (float)
            joint_id = params.get("joint_id", 0)
            angle = float(params.get("angle", 0))
            body = b'\x03' + struct.pack('<Bf', joint_id, angle)
        elif cmd == "gait":
            gait_id = params.get("gait_id", 0)
            body = b'\x04' + struct.pack('<B', gait_id)
        elif cmd == "action":
            action_id = params.get("action_id", 0)
            body = b'\x05' + struct.pack('<B', action_id)
        # ... other commands as per the device
        else:
            return JSONResponse({"error": "Unknown command type"}, status_code=400)
        # Add header, length, and checksum as per protocol
        # Example: header(2) + length(1) + body + checksum(1)
        pkt = COMMAND_HEADER + struct.pack('<B', len(body)) + body
        checksum = sum(pkt) & 0xFF
        pkt += struct.pack('<B', checksum)
        reply = send_udp_message(pkt, expect_reply=True, reply_size=256)
        if reply is None:
            return JSONResponse({"status": "timeout", "sent": pkt.hex()}, status_code=504)
        return JSONResponse({"status": "ok", "sent": pkt.hex(), "reply": reply.hex()})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@app.get("/state")
async def get_state():
    """
    Retrieve the overall robot state including its current posture, joint angles,
    joint velocities, position, and gait status.
    """
    reply = send_udp_message(STATE_REQUEST, expect_reply=True, reply_size=512)
    if reply is None:
        return JSONResponse({"error": "timeout"}, status_code=504)
    state = parse_state(reply)
    return JSONResponse(state)

@app.get("/sensors")
async def get_sensors(type: Optional[str] = Query(None, description="Filter sensor type, e.g., imu")):
    """
    Fetch sensor data from the robot such as IMU readings, battery levels, and velocity measurements.
    Users can use query parameters for filtering specific sensor data, e.g., ?type=imu.
    """
    reply = send_udp_message(SENSOR_REQUEST, expect_reply=True, reply_size=512)
    if reply is None:
        return JSONResponse({"error": "timeout"}, status_code=504)
    sensors = parse_sensors(reply)
    if type and type in sensors:
        return JSONResponse({type: sensors[type]})
    return JSONResponse(sensors)

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=HTTP_SERVER_HOST,
        port=HTTP_SERVER_PORT,
        log_level="info"
    )