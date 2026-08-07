/* Generated from addresses.json by generate_addresses.py — do not edit directly.
 * Edit addresses.json and re-run the generator instead.
 */

#ifndef ADDRESSES_HPP
#define ADDRESSES_HPP

const uint8_t sync = 0x55;
const uint8_t master = 0xff;

// Symbolic labels for sources[]/destinations[] below -- each is
// its device class's own lowest block-base pid (e.g. current's
// own cntl0cur pid), used purely as a distinguishing tag here,
// never compared against pids[]/messagebytes[] entries. Mirrors
// the class names used in linaddresses.py, just as uint8_t
// values since C can't put strings in a uint8_t[].
const uint8_t current = 0x20;
const uint8_t light = 0x30;
const uint8_t motor = 0x00;

const uint8_t cntl0mot = 0x00;
const uint8_t cntl1mot = 0x04;
const uint8_t cntl2mot = 0x08;
const uint8_t cntl3mot = 0x0C;
const uint8_t st0mot = 0x10;
const uint8_t st1mot = 0x14;
const uint8_t st2mot = 0x18;
const uint8_t cntl0cur = 0x20;
const uint8_t st0cur = 0x24;
const uint8_t cntl0lig = 0x30;
const uint8_t st0lig = 0x34;

const uint8_t pids[] = {cntl0mot, cntl1mot, cntl2mot, cntl3mot, st0mot, st1mot, st2mot, cntl0cur, st0cur, cntl0lig, st0lig};
const uint8_t messagebytes[] = {2, 2, 6, 2, 3, 2, 2, 2, 4, 2, 4};

const uint8_t sources[] = {master, master, master, master, motor, motor, motor, master, current, master, light};
const uint8_t destinations[] = {motor, motor, motor, motor, master, master, master, current, master, light, master};

// This board's own instance id (0x00, 0x01, ...) is read at startup from hardware strap pins -- look up the right table below for the device class this firmware actually is.
const uint8_t current_instances[] = {0x00, 0x01};
const uint8_t light_instances[] = {0x00, 0x01};
const uint8_t motor_instances[] = {0x00, 0x01, 0x02, 0x03};

#endif
