import os
import struct
import json
import socket
from flask import Flask, request, Response, jsonify, stream_with_context, abort

# --- Configuration from environment variables ---
ROBOT_UDP_IP = os.environ.get("ROBOT_UDP_IP", "127.0.0.1")
ROBOT_UDP_PORT = int(os.environ.get("ROBOT_UDP_PORT", "50010"))
HTTP_SERVER_HOST = os.environ.get("HTTP_SERVER_HOST", "0.0.0.0")
HTTP_SERVER_PORT = int(os.environ.get("HTTP_SERVER_PORT", "8080"))
UDP_TIMEOUT = float(os.environ.get("UDP_TIMEOUT", "2.0"))
ROBOT_UDP_BUFFER_SIZE = int(os.environ.get("ROBOT_UDP_BUFFER_SIZE", "4096"))

app = Flask(__name__)

# --- UDP Communication Helpers ---

def send_udp_command(command_bytes):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(UDP_TIMEOUT)
    try:
        sock.sendto(command_bytes, (ROBOT_UDP_IP, ROBOT_UDP_PORT))
        response, _ = sock.recvfrom(ROBOT_UDP_BUFFER_SIZE)
        return response
    except socket.timeout:
        return None
    finally:
        sock.close()

def send_udp_command_no_response(command_bytes):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.sendto(command_bytes, (ROBOT_UDP_IP, ROBOT_UDP_PORT))
    finally:
        sock.close()

# --- Binary Protocol (Example) ---
# NOTE: In practice, you would replace these with the actual protocol/structs per device documentation.

def build_command_packet(command_type, params):
    """
    Build the binary command packet.
    This is a placeholder: actual format depends on device documentation.
    """
    # Example: [CMD_TYPE (1B)] + [payload_length (2B)] + [payload...]
    payload = json.dumps(params).encode('utf-8')
    packet = struct.pack('<B', command_type) + struct.pack('<H', len(payload)) + payload
    return packet

def parse_state_packet(data):
    """
    Parse binary state data into a JSON-able dict.
    This is a placeholder: replace struct format and fields with actual device protocol.
    """
    # Example: [posture (4f)] + [joint_angles (12f)] + [joint_velocities (12f)] + [position (3f)] + [gait_status (B)]
    # You need to know the actual struct! We'll mock it here for demonstration.
    try:
        offset = 0
        posture = struct.unpack_from('<4f', data, offset); offset += 16
        joint_angles = struct.unpack_from('<12f', data, offset); offset += 48
        joint_velocities = struct.unpack_from('<12f', data, offset); offset += 48
        position = struct.unpack_from('<3f', data, offset); offset += 12
        gait_status = struct.unpack_from('<B', data, offset)[0]; offset += 1
        return {
            'posture': posture,
            'joint_angles': joint_angles,
            'joint_velocities': joint_velocities,
            'position': position,
            'gait_status': gait_status,
        }
    except Exception:
        return {'error': 'Failed to parse state packet', 'raw': data.hex()}

def parse_sensors_packet(data, sensor_type=None):
    """
    Parse binary sensor data. Returns dict.
    This is a placeholder: actual struct format required.
    """
    # Example layout: [imu (9f)] + [battery (2f)] + [velocity (3f)]
    try:
        offset = 0
        imu = struct.unpack_from('<9f', data, offset); offset += 36
        battery = struct.unpack_from('<2f', data, offset); offset += 8
        velocity = struct.unpack_from('<3f', data, offset); offset += 12
        sensors = {
            'imu': imu,
            'battery': battery,
            'velocity': velocity,
        }
        if sensor_type in sensors:
            return {sensor_type: sensors[sensor_type]}
        return sensors
    except Exception:
        return {'error': 'Failed to parse sensor packet', 'raw': data.hex()}

# --- API Endpoints ---

@app.route('/command', methods=['POST'])
def command():
    """
    Submit operational commands to the robot.
    Expects JSON: {"command_type": <int>, "params": {...}}
    """
    data = request.get_json()
    if not data or 'command_type' not in data:
        return jsonify({'error': 'Missing command_type'}), 400
    command_type = data['command_type']
    params = data.get('params', {})
    cmd_packet = build_command_packet(command_type, params)
    # Most commands might not require a response
    send_udp_command_no_response(cmd_packet)
    return jsonify({'status': 'OK'})

@app.route('/state', methods=['GET'])
def state():
    """
    Retrieve robot state, returns JSON.
    """
    # Command type 0x01 = STATE_REQUEST (example)
    cmd_packet = build_command_packet(0x01, {})
    resp = send_udp_command(cmd_packet)
    if resp is None:
        return jsonify({'error': 'No response from robot'}), 504
    parsed = parse_state_packet(resp)
    return jsonify(parsed)

@app.route('/sensors', methods=['GET'])
def sensors():
    """
    Fetch sensor data. Query param: ?type=imu|battery|velocity
    """
    sensor_type = request.args.get('type')
    # Command type 0x02 = SENSORS_REQUEST (example)
    cmd_packet = build_command_packet(0x02, {'type': sensor_type} if sensor_type else {})
    resp = send_udp_command(cmd_packet)
    if resp is None:
        return jsonify({'error': 'No response from robot'}), 504
    parsed = parse_sensors_packet(resp, sensor_type)
    return jsonify(parsed)

# --- HTTP Server Entrypoint ---

if __name__ == '__main__':
    app.run(host=HTTP_SERVER_HOST, port=HTTP_SERVER_PORT)