import argparse

BRIGHTNESS_FILE = "/sys/class/backlight/intel_backlight/brightness"
MAX_BRIGHTNESS_FILE = "/sys/class/backlight/intel_backlight/max_brightness"

parser = argparse.ArgumentParser()
parser.add_argument('step', type=float, help="Percentage to change brightness")

args = parser.parse_args()

with open(BRIGHTNESS_FILE, 'r') as bfile:
    brightness = int(bfile.read().rstrip())
with open(MAX_BRIGHTNESS_FILE, 'r') as bfile:
    max_brightness = int(bfile.read().rstrip())

brightness += int(args.step * max_brightness)
brightness = min(max(brightness, 0), max_brightness)

with open(BRIGHTNESS_FILE, 'w') as bfile:
    bfile.write(str(brightness) + '\n')
