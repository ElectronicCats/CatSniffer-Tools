import serial
import time
import sys

ser = None
running = True


def start_sender():
    global ser
    ser = serial.Serial("/dev/tty.usbmodem133201", 115200)
    print("Serial port opened")
    while running:
        ser.write(b"set_tx_ascii loraIsComingUp\n\r")
        print("Message sent")
        time.sleep(1)
        ser.write(b"set_tx_ascii pwnlabs\n\r")
        print("Message sent")
        time.sleep(1)


if __name__ == "__main__":
    try:
        start_sender()
    except KeyboardInterrupt:
        ser.close()
        sys.exit()
