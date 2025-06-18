import os
import io
import threading
import json
import time
import numpy as np
from flask import Flask, Response, jsonify, stream_with_context
import pyrealsense2 as rs
from PIL import Image

# Device Info
DEVICE_INFO = {
    "device_name": "Intel RealSense D455",
    "device_model": "D455",
    "manufacturer": "Intel",
    "device_type": "Depth Camera",
    "capabilities": {
        "streams": ["depth", "rgb", "imu"],
        "depth_format": "16-bit grayscale (mm)",
        "rgb_format": "YUV or RGB",
        "imu_format": "real-time sensor values"
    }
}

# Load environment variables for configuration
SERVER_HOST = os.environ.get('SERVER_HOST', '0.0.0.0')
SERVER_PORT = int(os.environ.get('SERVER_PORT', 8080))
DEPTH_WIDTH = int(os.environ.get('DEPTH_WIDTH', 1280))
DEPTH_HEIGHT = int(os.environ.get('DEPTH_HEIGHT', 720))
DEPTH_FPS = int(os.environ.get('DEPTH_FPS', 30))
COLOR_WIDTH = int(os.environ.get('COLOR_WIDTH', 1280))
COLOR_HEIGHT = int(os.environ.get('COLOR_HEIGHT', 800))
COLOR_FPS = int(os.environ.get('COLOR_FPS', 30))

app = Flask(__name__)

# RealSense pipeline and state
pipeline = rs.pipeline()
config = rs.config()
config.enable_stream(rs.stream.depth, DEPTH_WIDTH, DEPTH_HEIGHT, rs.format.z16, DEPTH_FPS)
config.enable_stream(rs.stream.color, COLOR_WIDTH, COLOR_HEIGHT, rs.format.rgb8, COLOR_FPS)
config.enable_stream(rs.stream.accel)
config.enable_stream(rs.stream.gyro)
profile = pipeline.start(config)
align = rs.align(rs.stream.color)

# Latest IMU data thread-safe store
imu_data = {"accel": None, "gyro": None}
imu_lock = threading.Lock()
imu_running = True

def imu_listener():
    global imu_running
    while imu_running:
        frames = pipeline.wait_for_frames()
        for f in frames:
            if f.is_motion_frame():
                motion = f.as_motion_frame()
                sensor_type = f.profile.stream_type()
                data = motion.get_motion_data()
                with imu_lock:
                    if sensor_type == rs.stream.accel:
                        imu_data["accel"] = {
                            "x": data.x,
                            "y": data.y,
                            "z": data.z,
                            "timestamp": f.get_timestamp()
                        }
                    elif sensor_type == rs.stream.gyro:
                        imu_data["gyro"] = {
                            "x": data.x,
                            "y": data.y,
                            "z": data.z,
                            "timestamp": f.get_timestamp()
                        }
        time.sleep(0.001)

imu_thread = threading.Thread(target=imu_listener, daemon=True)
imu_thread.start()

@app.route('/info', methods=['GET'])
def get_info():
    return jsonify(DEVICE_INFO)

def get_rgb_frame():
    for _ in range(10):
        frames = pipeline.wait_for_frames()
        aligned_frames = align.process(frames)
        color_frame = aligned_frames.get_color_frame()
        if color_frame:
            color_image = np.asanyarray(color_frame.get_data())
            img = Image.fromarray(color_image, 'RGB')
            buf = io.BytesIO()
            img.save(buf, format='JPEG')
            buf.seek(0)
            return buf.read()
    return None

@app.route('/rgb', methods=['GET'])
def rgb():
    img_bytes = get_rgb_frame()
    if img_bytes is None:
        return Response("Could not retrieve RGB frame", status=503)
    return Response(img_bytes, mimetype='image/jpeg')

def get_depth_frame():
    for _ in range(10):
        frames = pipeline.wait_for_frames()
        aligned_frames = align.process(frames)
        depth_frame = aligned_frames.get_depth_frame()
        if depth_frame:
            depth_image = np.asanyarray(depth_frame.get_data())
            img = Image.fromarray(depth_image.astype(np.uint16), mode='I;16')
            buf = io.BytesIO()
            img.save(buf, format='PNG')
            buf.seek(0)
            return buf.read()
    return None

@app.route('/depth', methods=['GET'])
def depth():
    png_bytes = get_depth_frame()
    if png_bytes is None:
        return Response("Could not retrieve depth frame", status=503)
    return Response(png_bytes, mimetype='image/png')

@app.route('/imu', methods=['GET'])
def imu():
    with imu_lock:
        data = {
            "accelerometer": imu_data.get("accel"),
            "gyroscope": imu_data.get("gyro")
        }
    return jsonify(data)

def cleanup():
    global imu_running
    imu_running = False
    imu_thread.join(timeout=1)
    pipeline.stop()

import atexit
atexit.register(cleanup)

if __name__ == '__main__':
    try:
        app.run(host=SERVER_HOST, port=SERVER_PORT, threaded=True)
    finally:
        cleanup()