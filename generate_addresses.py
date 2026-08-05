"""Generates addresses.md (a human "at a glance" occupied/free PID map)
plus draft linaddresses.py/addresses.h files from addresses.json — the
single source of truth for LIN PIDs, message sizes, and source/
destination pairs. See root CLAUDE.md's LIN Protocol "Address Table
Single Source of Truth" section for why this exists.

Addressing model (confirmed 2026-08-05): addresses.h/linaddresses.py
only get the per-message-type BASE PIDs, generated/compiled in as
usual. The actual on-wire PID for a specific unit (which motor, which
current sensor, ...) is computed at RUNTIME: each board reads its own
instance number from hardware strap pins (STM32: PB14/PB15, see
STM32/CLAUDE.md's "Instance-Selection Jumper" section) and ORs it
into the base PID itself — nothing here bakes in all instances' PIDs at
once. This is what lets multiple physical units share byte-identical
firmware.

Draft outputs go to generated/ (gitignored), NEVER directly to the real
raspi/control/linaddresses.py, STM32/firmware/Core/Inc/addresses.h, or
currentsensor/firmware/addresses.h — this is a deliberate, temporary
safety measure while this new addressing scheme is still being reviewed
by hand. Only start writing directly to the real files once explicitly
told to.

Run from the repo root: python generate_addresses.py
"""
import json
from pathlib import Path

REPO_ROOT = Path(__file__).parent
JSON_PATH = REPO_ROOT / "addresses.json"

GENERATED_DIR = REPO_ROOT / "generated"
PY_OUTPUT = GENERATED_DIR / "linaddresses.py"
# One single addresses.h, byte-for-byte identical for every embedded
# target (STM32, currentsensor, lightsensor, ...) -- contains every
# message across every device class, not just "its own". No filtering
# needed: message names are already globally unique, unused const
# uint8_t's cost ~nothing, and firmware already decides what to act on
# via PID comparison regardless of what else happens to be declared in
# the header. This is what makes "one generated artifact, copied
# everywhere, impossible to drift" actually true.
C_OUTPUT = GENERATED_DIR / "addresses.h"
MD_OUTPUT = REPO_ROOT / "addresses.md"

PY_HEADER_COMMENT = (
    "# DRAFT, generated from addresses.json by generate_addresses.py.\n"
    "# Not yet reviewed/adopted -- do not deploy or import as-is.\n"
)
C_HEADER_COMMENT = (
    "/* DRAFT, generated from addresses.json by generate_addresses.py.\n"
    " * Not yet reviewed/adopted -- do not build or flash as-is.\n"
    " */\n"
)


def instances_for(data, device_class):
    # Messages whose source/destination names a device class (e.g.
    # "motor") get expanded across every instances[] entry with a
    # matching "class" -- via base_pid | instance["id"], computed at
    # runtime by whichever board that instance actually is, not baked
    # in here. See module docstring.
    return [i for i in data["instances"] if i["class"] == device_class]


def render_markdown_check(data):
    # Human "at a glance" view of the PID space: which 4-slot blocks
    # (2 bits reserved for instance selection) are occupied, by what,
    # and how many slots within each block are still free. Generated,
    # not hand-maintained — see module docstring.
    messages = data["messages"]

    by_block_base = {int(m["pid"], 16) - (int(m["pid"], 16) % 4): m for m in messages}
    max_pid = max(int(m["pid"], 16) for m in messages)
    last_block = ((max_pid // 4) + 4) * 4  # some headroom past the last used block

    lines = [
        "<!-- Generated from addresses.json by generate_addresses.py — do "
        "not edit directly. Edit addresses.json and re-run the generator "
        "instead. -->",
        "",
        "# LIN Address Map (generated check)",
        "",
        "One block = 4 consecutive PIDs (2 bits reserved for instance "
        "selection — see root `CLAUDE.md`'s LIN Protocol section).",
        "",
        "| block | message | instances | occupied PIDs | free in block |",
        "|---|---|---|---|---|",
    ]

    block = 0
    while block <= last_block:
        m = by_block_base.get(block)
        if m is None:
            lines.append(f"| 0x{block:02x}-0x{block + 3:02x} | *(free)* | - | - | 4 |")
        else:
            instances = instances_for(data, m["destination"]) or instances_for(data, m["source"])
            names = [f"{i['class']}{i['num']}" for i in instances]
            occupied = [f"0x{(block | int(i['id'], 16)):02x}" for i in instances]
            lines.append(
                f"| 0x{block:02x}-0x{block + 3:02x} | `{m['name']}` | "
                f"{', '.join(names)} | {', '.join(occupied)} | "
                f"{4 - len(instances)} |"
            )
        block += 4

    lines.append("")
    return "\n".join(lines)


def render_python(data):
    # Master's view (raspi) -- needs every message type across every
    # device class, since it's the one side that ever needs to address
    # a *specific* unit (pick which motor/sensor to talk to).
    messages = data["messages"]
    classes = sorted(
        ({m["source"] for m in messages} | {m["destination"] for m in messages})
        - {"master"}
    )

    lines = [PY_HEADER_COMMENT, "class constants:", ""]
    lines.append(f"    sync = {data['sync']}")
    lines.append(f"    master = {data['master']}")
    lines.append("")
    for m in messages:
        lines.append(f"    {m['name']} = {m['pid']}")
    lines.append("")
    lines.append(f"    pids = [{', '.join(m['name'] for m in messages)}]")
    lines.append(f"    messagebytes = [{', '.join(str(m['bytes']) for m in messages)}]")
    lines.append("")
    lines.append("    # source/destination are always strings (including \"master\") --")
    lines.append("    # they name a device *class*, not a fixed wire address. Combine")
    lines.append("    # a message's base pid with the target instance's id below to")
    lines.append("    # get the actual on-wire pid.")
    lines.append(
        "    sources = ["
        + ", ".join(repr(m["source"]) for m in messages)
        + "]"
    )
    lines.append(
        "    destinations = ["
        + ", ".join(repr(m["destination"]) for m in messages)
        + "]"
    )
    lines.append("")
    for cls in classes:
        insts = instances_for(data, cls)
        pairs = ", ".join(f"{i['num']}: {i['id']}" for i in insts)
        lines.append(f"    {cls}_instances = {{{pairs}}}")
    lines.append("")
    return "\n".join(lines)


def render_c_header(data):
    # ONE universal header -- every message across every device class,
    # not filtered per target. See C_OUTPUT's comment above for why.
    messages = data["messages"]
    classes = sorted(
        ({m["source"] for m in messages} | {m["destination"] for m in messages})
        - {"master"}
    )

    lines = [
        C_HEADER_COMMENT,
        "#ifndef ADDRESSES_HPP",
        "#define ADDRESSES_HPP",
        "",
        f"const uint8_t sync = {data['sync']};",
        f"const uint8_t master = {data['master']};",
        "",
        "// Symbolic labels for sources[]/destinations[] below -- NOT real",
        "// wire addresses (those come from combining a message's base pid",
        "// with an instance id at runtime). Mirrors the class names used",
        "// in linaddresses.py, just as small distinct uint8_t sentinels",
        "// since C can't put strings in a uint8_t[].",
    ]
    for i, cls in enumerate(classes, start=1):
        lines.append(f"const uint8_t {cls} = {i};")
    lines.append("")
    for m in messages:
        lines.append(f"const uint8_t {m['name']} = {m['pid']};")
    lines.append("")
    lines.append(f"const uint8_t pids[] = {{{', '.join(m['name'] for m in messages)}}};")
    lines.append(f"const uint8_t messagebytes[] = {{{', '.join(str(m['bytes']) for m in messages)}}};")
    lines.append("")
    lines.append(
        f"const uint8_t sources[] = {{{', '.join(m['source'] for m in messages)}}};"
    )
    lines.append(
        f"const uint8_t destinations[] = {{{', '.join(m['destination'] for m in messages)}}};"
    )
    lines.append("")
    lines.append(
        "// This board's own instance id (0x00, 0x01, ...) is read at "
        "startup from hardware strap pins -- look up the right table "
        "below for the device class this firmware actually is."
    )
    for cls in classes:
        insts = instances_for(data, cls)
        lines.append(f"const uint8_t {cls}_instances[] = {{{', '.join(i['id'] for i in insts)}}};")
    lines.append("")
    lines.append("#endif")
    lines.append("")
    return "\n".join(lines)


def main():
    # Explicit UTF-8 everywhere — Path.read_text()/write_text() default to
    # the OS locale encoding, which mangles the em dash in the generated
    # header comments on Windows (cp1252).
    data = json.loads(JSON_PATH.read_text(encoding="utf-8"))

    MD_OUTPUT.write_text(render_markdown_check(data), encoding="utf-8")
    print(f"wrote {MD_OUTPUT}")

    GENERATED_DIR.mkdir(exist_ok=True)

    PY_OUTPUT.write_text(render_python(data), encoding="utf-8")
    print(f"wrote {PY_OUTPUT} (draft -- not the real raspi/control/linaddresses.py)")

    C_OUTPUT.write_text(render_c_header(data), encoding="utf-8")
    print(f"wrote {C_OUTPUT} (draft -- same file for every embedded target, "
          f"not the real STM32/currentsensor/lightsensor addresses.h)")


if __name__ == "__main__":
    main()
