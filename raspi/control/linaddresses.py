# Generated from addresses.json by generate_addresses.py — do not edit directly.
# Edit addresses.json and re-run the generator instead.

class constants:

    sync = 0x55
    master = 0xff

    cntl0mot = 0x00
    cntl1mot = 0x04
    cntl2mot = 0x08
    cntl3mot = 0x0C
    st0mot = 0x10
    st1mot = 0x14
    st2mot = 0x18
    cntl0cur = 0x20
    st0cur = 0x24
    cntl0lig = 0x30
    st0lig = 0x34

    pids = [cntl0mot, cntl1mot, cntl2mot, cntl3mot, st0mot, st1mot, st2mot, cntl0cur, st0cur, cntl0lig, st0lig]
    messagebytes = [2, 2, 6, 2, 3, 2, 2, 2, 4, 2, 4]

    # source/destination are always strings (including "master") --
    # they name a device *class*, not a fixed wire address. Combine
    # a message's base pid with the target instance's id below to
    # get the actual on-wire pid.
    sources = ['master', 'master', 'master', 'master', 'motor', 'motor', 'motor', 'master', 'current', 'master', 'light']
    destinations = ['motor', 'motor', 'motor', 'motor', 'master', 'master', 'master', 'current', 'master', 'light', 'master']

    current_instances = {0: 0x00, 1: 0x01}
    light_instances = {0: 0x00, 1: 0x01}
    motor_instances = {0: 0x00, 1: 0x01, 2: 0x02, 3: 0x03}
