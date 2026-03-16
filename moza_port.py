import hid
import time

VENDOR_ID = 0x346E     # MOZA
PRODUCT_ID = None      # auto-detect

print("Searching for MOZA device...")

for d in hid.enumerate():
    if d['vendor_id'] == VENDOR_ID:
        PRODUCT_ID = d['product_id']
        print("Found:", d['product_string'])
        break

if PRODUCT_ID is None:
    print("MOZA device not found")
    exit()

dev = hid.device()
dev.open(VENDOR_ID, PRODUCT_ID)
dev.set_nonblocking(True)

print("\nConnected")
print("Leave wheel untouched for baseline...\n")

time.sleep(2)

# get baseline packet
baseline = None
while baseline is None:
    data = dev.read(64)
    if data:
        baseline = data

print("Baseline captured\n")
print("Now press buttons or move pedals/steering\n")

mapping = {}

def detect_changes(old, new):
    changes = []

    for i in range(len(new)):
        if old[i] != new[i]:

            diff = old[i] ^ new[i]

            for bit in range(8):
                if diff & (1 << bit):
                    state = (new[i] >> bit) & 1
                    changes.append((i, bit, state))

    return changes


while True:

    data = dev.read(64)

    if not data:
        continue

    # detect axis changes
    # for i in range(len(data)):
    #     delta = abs(data[i] - baseline[i])

    #     if delta > 5:
    #         print(f"Axis movement detected at BYTE {i} value {data[i]}")

    # detect button changes
    changes = detect_changes(baseline, data)

    for byte, bit, state in changes:

        key = f"byte{byte}_bit{bit}"

        if key not in mapping:
            mapping[key] = True
            print(f"Button discovered -> BYTE {byte} BIT {bit}")

    baseline = data