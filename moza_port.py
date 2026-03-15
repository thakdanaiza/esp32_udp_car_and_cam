#!/usr/bin/env python3
"""
Simple HID reader for Moza Racing Sim devices.
Reads raw input data from the device (steering, pedals, buttons, etc.)
Displays visual bars for steering, throttle, and brake.
Sends control commands to Arduino via serial.
"""

import hid
import time
import sys
import os
import struct
import serial
import serial.tools.list_ports

import time
import math
import matplotlib.pyplot as plt
from collections import deque

# state
yaw = 0.0
vx = vy = 0.0
x = y = 0.0

last_t = time.time()

# history for plotting
N = 500
ax_h = deque(maxlen=N)
ay_h = deque(maxlen=N)
yaw_h = deque(maxlen=N)
x_h  = deque(maxlen=N)
y_h  = deque(maxlen=N)

# Moza Racing vendor ID (common ones)
MOZA_VENDOR_IDS = [0x346E]  # Moza Racing VID

# Arduino vendor IDs (common ones)
ARDUINO_VIDS = [0x2341, 0x2A03, 0x1A86, 0x10C4, 0x0403, 0x067B]  # Arduino, CH340, CP210x, FTDI, Prolific

# Bar display settings
BAR_WIDTH = 50
STEERING_BAR_WIDTH = 50

# Serial settings
SERIAL_BAUDRATE = 115200
SERIAL_UPDATE_MS = 10  # 10ms update rate (100Hz)


def find_arduino_port():
    """Find connected Arduino serial port."""
    ports = serial.tools.list_ports.comports()
    
    arduino_ports = []
    
    for port in ports:
        if "COM9" in port.description:
            arduino_ports.append(port)
    
    return arduino_ports


def list_serial_ports():
    """List all available serial ports."""
    ports = serial.tools.list_ports.comports()
    print("\nAvailable Serial Ports:")
    print("-" * 50)
    
    for port in ports:
        vid_str = f"0x{port.vid:04X}" if port.vid else "N/A"
        print(f"  {port.device}: {port.description} (VID: {vid_str})")
    
    return ports


def clear_line():
    """Move cursor up and clear line."""
    sys.stdout.write('\033[F\033[K')


def draw_steering_bar(value, min_val=0, max_val=65535):
    """
    Draw a centered steering bar.
    Value at center = straight, left/right shows turn direction.
    """
    # Avoid division by zero
    if max_val == min_val:
        normalized = 0.5
    else:
        normalized = (value - min_val) / (max_val - min_val)  # 0.0 to 1.0
    
    # Clamp to valid range
    normalized = max(0.0, min(1.0, normalized))
    
    center_pos = STEERING_BAR_WIDTH // 2
    
    # Calculate position (0 = full left, center = straight, max = full right)
    pos = int(normalized * STEERING_BAR_WIDTH)
    
    bar = [' '] * STEERING_BAR_WIDTH
    bar[center_pos] = '|'  # Center marker
    
    if pos < center_pos:
        # Turning left
        for i in range(pos, center_pos):
            bar[i] = '█'
    elif pos > center_pos:
        # Turning right
        for i in range(center_pos + 1, min(pos + 1, STEERING_BAR_WIDTH)):
            bar[i] = '█'
    
    bar_str = ''.join(bar)
    percentage = (normalized - 0.5) * 200  # -100% to +100%
    direction = "LEFT " if percentage < -1 else "RIGHT" if percentage > 1 else "CENTER"
    
    return f"[{bar_str}] {percentage:+6.1f}% {direction}"


def draw_pedal_bar(value, max_val=255, label="", color_code=""):
    """Draw a horizontal progress bar for pedal input."""
    if max_val == 0:
        percentage = 0
    else:
        percentage = min(100, (value / max_val) * 100)
    
    filled = int((percentage / 100) * BAR_WIDTH)
    empty = BAR_WIDTH - filled
    
    bar = '█' * filled + '░' * empty
    return f"{label:10} [{bar}] {percentage:5.1f}%"


def list_hid_devices():
    """List all connected HID devices."""
    print("=" * 70)
    print("Available HID Devices:")
    print("=" * 70)
    
    devices = hid.enumerate()
    moza_devices = []
    
    for i, device in enumerate(devices):
        vid = device['vendor_id']
        pid = device['product_id']
        manufacturer = device.get('manufacturer_string', 'Unknown')
        product = device.get('product_string', 'Unknown')
        
        # Check if it's a Moza device
        is_moza = vid in MOZA_VENDOR_IDS or 'moza' in str(product).lower() or 'moza' in str(manufacturer).lower()
        
        if is_moza:
            moza_devices.append(device)
            marker = " <-- MOZA DEVICE"
        else:
            marker = ""
        
        print(f"\n[{i}] VID: 0x{vid:04X}, PID: 0x{pid:04X}{marker}")
        print(f"    Manufacturer: {manufacturer}")
        print(f"    Product: {product}")
    
    print("\n" + "=" * 70)
    return devices, moza_devices


def read_device(device_info, serial_port=None):
    """Read data from a HID device, display visual bars, and send to Arduino."""
    vid = device_info['vendor_id']
    pid = device_info['product_id']
    product = device_info.get('product_string', 'Unknown')
    
    print(f"\nConnecting to: {product} (VID: 0x{vid:04X}, PID: 0x{pid:04X})")
    
    # Open serial port if provided
    ser = None
    if serial_port:
        try:
            ser = serial.Serial(serial_port, SERIAL_BAUDRATE, timeout=0.1)
            time.sleep(2)  # Wait for Arduino to reset
            print(f"Serial connected to: {serial_port} @ {SERIAL_BAUDRATE} baud")
        except Exception as e:
            print(f"Warning: Could not open serial port {serial_port}: {e}")
            ser = None
    
    try:
        # Open device
        device = hid.device()
        device.open_path(device_info['path'])
        device.set_nonblocking(True)
        
        print("Connected! Reading data... (Press Ctrl+C to stop)")
        print("Turn your wheel LEFT and RIGHT to calibrate steering range!")
        if ser:
            print(f"Sending commands to Arduino at {1000/SERIAL_UPDATE_MS:.0f}Hz\n")
        else:
            print("No Arduino connected - display only mode\n")
        
        # Initial display
        print("\n" * 16)  # Reserve space for display
        
        last_data = None
        last_serial_send = 0
        
        # Hardcoded steering range (from calibration)
        steering_min = 16777217
        steering_max = 33554177
        
        # Current values for serial output
        steering_out = 127  # 0-255, 127 = center
        throttle_out = 0    # 0-255, 0 = stop
        
        # Button states
        paddle_up = False
        paddle_down = False
        btn_n = False  # Neutral
        btn_r = False  # Reverse
        
        # Track previous button states for edge detection
        prev_paddle_up = False
        prev_paddle_down = False
        gear = 0  # Current gear (0=N, -1=R, 1-6=forward gears)
        
        while True:
            data = device.read(64)
            current_time = time.time() * 1000  # ms
            
            if data:
                last_data = data
                
                # Parse values (adjust these based on your device!)
                # Try 32-bit steering (little-endian) - Moza may use larger values
                if len(data) >= 4:
                    steering = (data[3] << 24) | (data[2] << 16) | (data[1] << 8) | data[0]
                elif len(data) >= 2:
                    steering = (data[1] << 8) | data[0]  # 16-bit steering
                else:
                    steering = 0
                
                # Use hardcoded steering range
                display_min = steering_min
                display_max = steering_max
                
                # ============================================
                # MOZA PEDAL - Signed 16-bit (int16_t)
                # Based on official SDK: throttle/brake are int16_t
                # Idle = 0x8000 (-32768), Full = 0x7FFF (+32767)
                # Throttle: bytes 5+6, Brake: bytes 11+12
                # ============================================
                if len(data) >= 13:
                    # Read as signed 16-bit little-endian
                    throttle_signed = struct.unpack('<h', bytes([data[5], data[6]]))[0]
                    brake_signed = struct.unpack('<h', bytes([data[11], data[12]]))[0]
                    
                    # Convert from [-32768, 32767] to [0, 65535]
                    throttle = throttle_signed + 32768
                    brake = brake_signed + 32768
                else:
                    throttle = 0
                    brake = 0
                
                # ============================================
                # BUTTONS & PADDLES
                # Common HID button byte positions (adjust as needed)
                # Buttons are typically bitmasks in specific bytes
                # ============================================
                if len(data) >= 16:
                    # Try common button byte positions
                    # Adjust these based on actual data observation
                    btn_byte1 = data[13] if len(data) > 13 else 0
                    btn_byte2 = data[14] if len(data) > 14 else 0
                    btn_byte3 = data[15] if len(data) > 15 else 0
                    
                    # Store previous states for edge detection
                    prev_paddle_up = paddle_up
                    prev_paddle_down = paddle_down
                    
                    # Common button mappings (these may need adjustment!)
                    # Usually paddles are in lower bits
                    paddle_up = bool(btn_byte1 & 0x01)     # Bit 0 - Paddle Up (shift up)
                    paddle_down = bool(btn_byte1 & 0x02)   # Bit 1 - Paddle Down (shift down)
                    btn_n = bool(btn_byte1 & 0x04)         # Bit 2 - N button (Neutral)
                    btn_r = bool(btn_byte1 & 0x08)         # Bit 3 - R button (Reverse)
                    
                    # Gear calculation based on paddle shifts
                    # Shift up on rising edge
                    if paddle_up and not prev_paddle_up:
                        if gear == -1:  # From R to N
                            gear = 0
                        elif gear < 6:  # Max 6 gears
                            gear += 1
                    
                    # Shift down on rising edge
                    if paddle_down and not prev_paddle_down:
                        if gear > -1:  # Min is -1 (R)
                            gear -= 1
                    
                    # N button sets neutral
                    if btn_n:
                        gear = 0
                    
                    # R button sets reverse
                    if btn_r:
                        gear = -1
                
                # ============================================
                # Convert to 0-255 for serial output
                # Steering: 0 = left, 127 = center, 255 = right
                # Throttle: 0 = stop, 255 = full
                # ============================================
                steering_range = display_max - display_min
                if steering_range > 0:
                    steering_normalized = (steering - display_min) / steering_range
                    steering_normalized = max(0.0, min(1.0, steering_normalized))
                    steering_out = int(steering_normalized * 255)
                else:
                    steering_out = 127
                
                # Throttle: map 0-65535 to 0-255
                throttle_out = int((throttle / 65535) * 255)
                throttle_out = max(0, min(255, throttle_out))
                
                # Move cursor up and redraw
                sys.stdout.write('\033[16F')  # Move up 16 lines
                
                # Show first 16 bytes with their indices for debugging
                raw_display = ""
                for i in range(min(16, len(data))):
                    raw_display += f"{i:2d}:{data[i]:3d} "
                
                # Serial status
                serial_status = f"Arduino: {serial_port}" if ser else "Arduino: Not connected"
                
                # Gear display
                if gear == 0:
                    gear_str = "N"
                elif gear == -1:
                    gear_str = "R"
                else:
                    gear_str = str(gear)
                
                # Button status display
                btn_status = f"[{'↑' if paddle_up else ' '}] UP  [{'↓' if paddle_down else ' '}] DN  [{'N' if btn_n else ' '}]  [{'R' if btn_r else ' '}]"
                
                # Draw the display
                print("┌" + "─" * 78 + "┐")
                print(f"│  STEERING  {draw_steering_bar(steering, display_min, display_max):64} │")
                print(f"│  Raw: {steering:12d}                                                            │")
                print("│" + " " * 78 + "│")
                print(f"│  {draw_pedal_bar(throttle, 65535, 'THROTTLE'):74} │")
                print(f"│  {draw_pedal_bar(brake, 65535, 'BRAKE'):74} │")
                print("│" + " " * 78 + "│")
                print(f"│  GEAR: [{gear_str:^3}]   Paddles: {btn_status:40} │")
                print("│" + " " * 78 + "│")
                print(f"│  Serial Output: <{steering_out:3d},{throttle_out:3d}>   {serial_status:40} │")
                print("│" + " " * 78 + "│")
                print(f"│  Raw bytes (index:value):                                                    │")
                print(f"│  {raw_display:76} │")
                print(f"│  Btn bytes: b13:{data[13] if len(data)>13 else 0:3d}  b14:{data[14] if len(data)>14 else 0:3d}  b15:{data[15] if len(data)>15 else 0:3d}  b16:{data[16] if len(data)>16 else 0:3d}                           │")
                print("└" + "─" * 78 + "┘")
                
            
            # Send serial command at 10ms intervals (100Hz)
            if ser and (current_time - last_serial_send) >= SERIAL_UPDATE_MS:
                command = f"<{steering_out},{throttle_out}>\n"
                try:
                    ser.write(command.encode())
                except Exception as e:
                    pass  # Ignore serial write errors
                last_serial_send = current_time
            
            # ---------- READ TELEMETRY FROM ESP32 ----------
            if ser and ser.in_waiting:
                try:
                    line = ser.readline().decode(errors="ignore").strip()
                    if line.startswith("TELE,"):
                        parts = line.split(',')
                        if len(parts) == 10:
                            ax    = float(parts[1])
                            ay    = float(parts[2])
                            az    = float(parts[3])
                            gx    = float(parts[4])
                            gy    = float(parts[5])
                            gz    = float(parts[6])
                            angle = float(parts[7])
                            omega = float(parts[8])
                            turns = int(parts[9])
                            print(f"IMU A[{ax:.2f},{ay:.2f},{az:.2f}] "
                                  f"G[{gx:.2f},{gy:.2f},{gz:.2f}] | "
                                  f"ENC deg={angle:.1f} w={omega:.1f}deg/s turns={turns}")
                    else:
                        print(line)
                except Exception:
                    pass
            sys.stdout.flush()

            time.sleep(0.001)  # 1ms loop for responsive serial timing
            
    except KeyboardInterrupt:
        print("\n\nStopped by user.")
        if last_data:
            print(f"Last raw data ({len(last_data)} bytes):")
            print(f"  {' '.join(f'{b:02X}' for b in last_data)}")
            print(f"\nCalibrated steering range: {steering_min} to {steering_max}")
    except Exception as e:
        print(f"\nError: {e}")
    finally:
        device.close()
        print("HID device closed.")
        if ser:
            ser.close()
            print("Serial port closed.")


def main():
    print("\n🏎️  Moza Racing Sim HID Reader + Arduino Controller")
    print("=" * 70)
    
    # Find Arduino serial port
    arduino_ports = find_arduino_port()
    serial_port = None
    
    if arduino_ports:
        serial_port = arduino_ports[0].device
        print(f"\nFound Arduino: {serial_port} ({arduino_ports[0].description})")
    else:
        print("\nNo Arduino detected. Running in display-only mode.")
        list_serial_ports()
    
    # List all HID devices
    all_devices, moza_devices = list_hid_devices()
    
    if not all_devices:
        print("No HID devices found!")
        sys.exit(1)
    
    # Auto-select first Moza device if found
    if moza_devices:
        print(f"\nFound {len(moza_devices)} Moza device(s)!")
        print("Auto-selecting first Moza device...")
        read_device(moza_devices[0], serial_port)
    else:
        # Fall back to manual selection if no Moza device found
        print("\nNo Moza devices auto-detected.")
        print("Select your device manually from the list above.")
        print("\nEnter device number to read from (or 'q' to quit): ", end="")
        
        try:
            choice = input().strip()
            if choice.lower() == 'q':
                print("Goodbye!")
                sys.exit(0)
            
            device_index = int(choice)
            if 0 <= device_index < len(all_devices):
                read_device(all_devices[device_index], serial_port)
            else:
                print(f"Invalid selection. Please enter 0-{len(all_devices)-1}")
        except ValueError:
            print("Invalid input. Please enter a number.")
        except KeyboardInterrupt:
            print("\nGoodbye!")


if __name__ == "__main__":
    main()
