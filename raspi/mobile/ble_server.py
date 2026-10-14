#!/usr/bin/env python3
"""MotorPi BLE peripheral using the system BlueZ D-Bus API (no pip dependencies)."""
import argparse
import json
import logging
import signal
import threading
import time

import dbus
import dbus.service
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib

from bridge import worker
from control_core import Config, Control, SERVICE_UUID, CHALLENGE_UUID, COMMAND_UUID, STATUS_UUID

PROPS = "org.freedesktop.DBus.Properties"
OBJECTS = "org.freedesktop.DBus.ObjectManager"
SERVICE = "org.bluez.GattService1"
CHAR = "org.bluez.GattCharacteristic1"
AD = "org.bluez.LEAdvertisement1"
ROOT = "/com/motorpi/mobile"
LOG = logging.getLogger("motorpi.mobile")


class Rejected(dbus.DBusException):
    _dbus_error_name = "org.bluez.Error.NotPermitted"


class Properties(dbus.service.Object):
    @dbus.service.method(PROPS, in_signature="s", out_signature="a{sv}")
    def GetAll(self, interface):
        return self.properties().get(interface, {})

    @dbus.service.method(PROPS, in_signature="ss", out_signature="v")
    def Get(self, interface, name):
        return self.GetAll(interface)[name]

    @dbus.service.signal(PROPS, signature="sa{sv}as")
    def PropertiesChanged(self, interface, changed, invalidated):
        pass


class Service(Properties):
    def __init__(self, bus):
        self.path = ROOT + "/service0"
        super().__init__(bus, self.path)

    def properties(self):
        return {SERVICE: {"UUID": SERVICE_UUID, "Primary": dbus.Boolean(True)}}


class Characteristic(Properties):
    def __init__(self, bus, service, index, uuid, flags, control, lock):
        self.path = service.path + "/char%d" % index
        self.service, self.uuid, self.flags = service, uuid, flags
        self.control, self.lock = control, lock
        self.notifying = False
        self.on_write = lambda: None
        super().__init__(bus, self.path)

    def properties(self):
        return {CHAR: {"UUID": self.uuid, "Service": dbus.ObjectPath(self.service.path),
                       "Flags": dbus.Array(self.flags, signature="s"),
                       "Notifying": dbus.Boolean(self.notifying)}}

    @dbus.service.method(CHAR, in_signature="a{sv}", out_signature="ay")
    def ReadValue(self, options):
        if int(options.get("offset", 0)) != 0:
            raise Rejected("Long reads are not supported")
        try:
            with self.lock:
                if self.uuid == CHALLENGE_UUID:
                    LOG.info("BLE session challenge requested")
                    value = self.control.challenge(str(options.get("device", "")))
                elif self.uuid == STATUS_UUID:
                    value = self.control.status()
                else:
                    raise ValueError("Write-only characteristic")
            return dbus.Array(value, signature="y")
        except ValueError as exc:
            LOG.warning("BLE read rejected: %s", exc)
            raise Rejected(str(exc))

    @dbus.service.method(CHAR, in_signature="aya{sv}", out_signature="")
    def WriteValue(self, value, options):
        if self.uuid != COMMAND_UUID or int(options.get("offset", 0)) != 0:
            raise Rejected("Invalid write")
        try:
            with self.lock:
                self.control.receive(str(options.get("device", "")), bytes(value))
            if len(value) == 17 and int(value[0]) == 0:
                LOG.info("BLE authentication accepted")
            self.on_write()
        except ValueError as exc:
            LOG.warning("BLE command rejected: %s", exc)
            raise Rejected(str(exc))
        except Exception:
            LOG.exception("BLE command failed")
            raise

    @dbus.service.method(CHAR, in_signature="", out_signature="")
    def StartNotify(self):
        if self.uuid != STATUS_UUID:
            raise Rejected("Notifications are only available for status")
        self.notifying = True

    @dbus.service.method(CHAR, in_signature="", out_signature="")
    def StopNotify(self):
        self.notifying = False

    def publish(self):
        if self.notifying:
            with self.lock:
                value = self.control.status()
            self.PropertiesChanged(CHAR, {"Value": dbus.Array(value, signature="y")}, [])
        return True


class Application(dbus.service.Object):
    def __init__(self, bus, children):
        super().__init__(bus, ROOT)
        self.children = children

    @dbus.service.method(OBJECTS, out_signature="a{oa{sa{sv}}}")
    def GetManagedObjects(self):
        return {dbus.ObjectPath(child.path): child.properties() for child in self.children}


class Advertisement(Properties):
    def __init__(self, bus):
        self.path = ROOT + "/advertisement0"
        super().__init__(bus, self.path)

    def properties(self):
        return {AD: {"Type": "peripheral", "LocalName": "MotorPi",
                     "ServiceUUIDs": dbus.Array([SERVICE_UUID], signature="s")}}

    @dbus.service.method(AD, in_signature="", out_signature="")
    def Release(self):
        LOG.info("Advertisement released")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="/etc/motorpi-mobile/config.json")
    parser.add_argument("--live", action="store_true",
                        help="Explicit per-start hardware consent; config must also authorize live mode")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    with open(args.config) as source:
        data = json.load(source)
    configured_live = data.get("live", False)
    data["live"] = bool(args.live and configured_live)
    if args.live and not configured_live:
        parser.error("The local configuration has not been commissioned for live control")
    config = Config(**data)
    control = Control(config, time.monotonic)
    lock, shutdown = threading.Lock(), threading.Event()
    DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()
    objects = dbus.Interface(bus.get_object("org.bluez", "/"), OBJECTS).GetManagedObjects()
    adapters = [path for path, interfaces in objects.items()
                if "org.bluez.GattManager1" in interfaces and "org.bluez.LEAdvertisingManager1" in interfaces]
    if not adapters:
        raise RuntimeError("No Bluetooth adapter with GATT peripheral/advertising support")
    adapter = bus.get_object("org.bluez", adapters[0])
    dbus.Interface(adapter, PROPS).Set("org.bluez.Adapter1", "Powered", dbus.Boolean(True))
    service = Service(bus)
    challenge = Characteristic(bus, service, 0, CHALLENGE_UUID, ["read"], control, lock)
    # Application-level acknowledgements (status sequence) work across old BlueZ
    # versions whose ATT Write Request replies can time out despite delivery.
    command = Characteristic(bus, service, 1, COMMAND_UUID, ["write-without-response"], control, lock)
    status = Characteristic(bus, service, 2, STATUS_UUID, ["read", "notify"], control, lock)
    command.on_write = status.publish
    app = Application(bus, [service, challenge, command, status])
    advertisement = Advertisement(bus)
    loop = GLib.MainLoop()
    registration_error = []

    def disconnected(interface, changes, invalidated, path=None):
        if interface == "org.bluez.Device1" and changes.get("Connected") is not None:
            LOG.info("BLE peer %s: %s", path, "connected" if changes["Connected"] else "disconnected")
            if not bool(changes["Connected"]):
                with lock:
                    control.disconnect(str(path))

    bus.add_signal_receiver(disconnected, dbus_interface=PROPS, signal_name="PropertiesChanged",
                            path_keyword="path")

    def registration_failed(error):
        registration_error.append(str(error))
        LOG.error("Bluetooth registration failed: %s", error)
        shutdown.set()
        loop.quit()

    manager = dbus.Interface(adapter, "org.bluez.GattManager1")
    advertiser = dbus.Interface(adapter, "org.bluez.LEAdvertisingManager1")
    manager.RegisterApplication(ROOT, {}, reply_handler=lambda: LOG.info("GATT service registered"),
                                error_handler=registration_failed)
    advertiser.RegisterAdvertisement(advertisement.path, {},
                                      reply_handler=lambda: LOG.info("MotorPi advertising active"),
                                      error_handler=registration_failed)
    thread = threading.Thread(target=worker, args=(control, lock, shutdown, LOG), daemon=True)
    thread.start()
    GLib.timeout_add(200, status.publish)

    def stop_service(signum, frame):
        with lock:
            control.ready = False
            control.stop()
        GLib.timeout_add(int(config.ramp_s * 1000) + 300, lambda: loop.quit())

    signal.signal(signal.SIGTERM, stop_service)
    signal.signal(signal.SIGINT, stop_service)
    LOG.info("Ready in %s mode", "LIVE" if config.live else "SIMULATION (no motor socket)")
    try:
        loop.run()
    finally:
        shutdown.set()
        thread.join(timeout=2)
        for obj, method, path in ((advertiser, "UnregisterAdvertisement", advertisement.path),
                                  (manager, "UnregisterApplication", ROOT)):
            try:
                getattr(obj, method)(path)
            except dbus.DBusException:
                pass
    if registration_error or (not thread.is_alive() and shutdown.is_set() and control.state == 3):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
