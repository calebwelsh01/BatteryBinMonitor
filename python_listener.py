#!/usr/bin/env python3
import serial
import subprocess
import time

SERIAL_PORT = "/dev/ttyUSB0"   # confirm with `ls /dev/tty*`
BAUD_RATE = 115200

def parse_battery_type(stdout_text):
    """Pull just the value after 'Battery type:' from the script's output."""
    for line in stdout_text.splitlines():
        line = line.strip()
        if line.lower().startswith("battery type:"):
            return line.split(":", 1)[1].strip()
    return "Unknown"

def run_identify_battery(ser):
    try:
        ser.write(b"UPLOAD_START\n")

        result = subprocess.run(
            ["python3", "identify_battery.py", "--upload"],
            capture_output=True, text=True, timeout=30
        )

        if result.stderr:
            print("stderr:", result.stderr)

        battery_type = parse_battery_type(result.stdout)

    except subprocess.TimeoutExpired:
        battery_type = "Timeout"
    except Exception as e:
        battery_type = "Error"
        print(f"Error: {e}")
    finally:
        ser.write(b"UPLOAD_DONE\n")

    return battery_type

def main():
    ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
    time.sleep(2)  # let the Mega reset after serial connect

    print("Listening for button trigger...")
    while True:
        if ser.in_waiting:
            line = ser.readline().decode(errors="ignore").strip()
            if line == "REQUEST_BATTERY":
                print("Button pressed — running identify_battery.py --upload")
                battery_type = run_identify_battery(ser)
                ser.write(f"BATTERY:{battery_type}\n".encode())
                print(f"Sent result: {battery_type}")

if __name__ == "__main__":
    main()
