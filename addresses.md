<!-- Generated from addresses.json by generate_addresses.py — do not edit directly. Edit addresses.json and re-run the generator instead. -->

# LIN Address Map (generated check)

One block = 4 consecutive PIDs (2 bits reserved for instance selection — see root `CLAUDE.md`'s LIN Protocol section).

| block | message | instances | occupied PIDs | free in block |
|---|---|---|---|---|
| 0x00-0x03 | `cntl0mot` | motor0, motor1, motor2, motor3 | 0x00, 0x01, 0x02, 0x03 | 0 |
| 0x04-0x07 | `cntl1mot` | motor0, motor1, motor2, motor3 | 0x04, 0x05, 0x06, 0x07 | 0 |
| 0x08-0x0b | `cntl2mot` | motor0, motor1, motor2, motor3 | 0x08, 0x09, 0x0a, 0x0b | 0 |
| 0x0c-0x0f | `cntl3mot` | motor0, motor1, motor2, motor3 | 0x0c, 0x0d, 0x0e, 0x0f | 0 |
| 0x10-0x13 | `st0mot` | motor0, motor1, motor2, motor3 | 0x10, 0x11, 0x12, 0x13 | 0 |
| 0x14-0x17 | `st1mot` | motor0, motor1, motor2, motor3 | 0x14, 0x15, 0x16, 0x17 | 0 |
| 0x18-0x1b | `st2mot` | motor0, motor1, motor2, motor3 | 0x18, 0x19, 0x1a, 0x1b | 0 |
| 0x1c-0x1f | `st3mot` | motor0, motor1, motor2, motor3 | 0x1c, 0x1d, 0x1e, 0x1f | 0 |
| 0x20-0x23 | `cntl0cur` | current0, current1 | 0x20, 0x21 | 2 |
| 0x24-0x27 | `st0cur` | current0, current1 | 0x24, 0x25 | 2 |
| 0x28-0x2b | `st1cur` | current0, current1 | 0x28, 0x29 | 2 |
| 0x2c-0x2f | *(free)* | - | - | 4 |
| 0x30-0x33 | `cntl0lig` | light0, light1 | 0x30, 0x31 | 2 |
| 0x34-0x37 | `st0lig` | light0, light1 | 0x34, 0x35 | 2 |
| 0x38-0x3b | *(free)* | - | - | 4 |
| 0x3c-0x3f | *(free)* | - | - | 4 |
| 0x40-0x43 | *(free)* | - | - | 4 |
| 0x44-0x47 | *(free)* | - | - | 4 |
