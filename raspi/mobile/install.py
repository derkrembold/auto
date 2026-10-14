#!/usr/bin/env python3
"""Install the WLAN control simulator and optional dedicated offline AP. Does not start motors."""
import argparse
import json
import os
from pathlib import Path
import pwd
import secrets
import shutil
import subprocess
from access_code import derive_key, generate_code


def run(*args):
    subprocess.run(args, check=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--access-point", action="store_true")
    parser.add_argument("--app-download", action="store_true")
    parser.add_argument("--rotate-access-code", action="store_true",
                        help="Generate a new eight-character app access code")
    parser.add_argument("--logs-only", action="store_true",
                        help="Install/restart only the read-only log service; allowed during a live session")
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error("Run with sudo")
    if args.logs_only:
        # Separate read-only process; touches neither the control server nor a live session.
        unit = Path(__file__).resolve().parent / "motorpi-logs.service"
        shutil.copyfile(str(unit), "/etc/systemd/system/motorpi-logs.service")
        run("systemctl", "daemon-reload")
        run("systemctl", "enable", "--now", "motorpi-logs.service")
        run("systemctl", "restart", "motorpi-logs.service")
        print("Installed the log service only (port 8081).")
        return
    # Restarting the simulator next to a consented live session would run two control servers.
    if subprocess.run(["systemctl", "is-active", "--quiet", "motorpi-driving-session"]).returncode == 0:
        parser.error("A live driving session is running; stop it before installing")
    source = Path(__file__).resolve().parent
    config_dir = Path("/etc/motorpi-mobile")
    config_dir.mkdir(mode=0o750, exist_ok=True)
    pi = pwd.getpwnam("pi")
    os.chown(str(config_dir), 0, pi.pw_gid)
    config_file = config_dir / "config.json"
    access = source / "access.txt"
    new_config = not config_file.exists()
    if new_config:
        config = json.loads((source / "config.example.json").read_text())
        config["key_hex"] = secrets.token_hex(16)
        config_file.write_text(json.dumps(config, indent=2) + "\n")
    config = json.loads(config_file.read_text())
    access_code = config["key_hex"]
    if access.exists():
        for line in access.read_text().splitlines():
            if line.startswith(("MotorPi access code: ", "MotorPi Bluetooth access code: ")):
                candidate = line.split(": ", 1)[1]
                if len(candidate) == 8 and derive_key(candidate).hex() == config["key_hex"]:
                    access_code = candidate
    if new_config or args.rotate_access_code:
        access_code = generate_code()
        config["key_hex"] = derive_key(access_code).hex()
        config_file.write_text(json.dumps(config, indent=2) + "\n")
    os.chmod(str(config_file), 0o640); os.chown(str(config_file), 0, pi.pw_gid)
    shutil.copyfile(str(source / "motorpi-mobile.service"), "/etc/systemd/system/motorpi-mobile.service")
    shutil.copyfile(str(source / "motorpi-logs.service"), "/etc/systemd/system/motorpi-logs.service")
    # The earlier BLE transport needed a D-Bus policy for BlueZ; WLAN control does not.
    old_dbus = Path("/etc/dbus-1/system.d/motorpi-mobile.conf")
    if old_dbus.exists():
        old_dbus.unlink()
        run("systemctl", "reload", "dbus")
    credentials = "MotorPi access code: " + access_code + "\nMode: SIMULATION\n"
    if args.access_point:
        # Ethernet is the maintenance connection. Never replace a Wi-Fi uplink silently.
        routes = subprocess.check_output(["ip", "route", "show", "default"], universal_newlines=True)
        if "dev eth0" not in routes or "dev wlan0" in routes:
            raise RuntimeError("Access-point setup requires the existing Ethernet uplink")
        hostapd = config_dir / "hostapd.conf"
        if not hostapd.exists():
            password = secrets.token_urlsafe(12)
            hostapd.write_text("interface=wlan0\ndriver=nl80211\nssid=MotorPi\ncountry_code=DE\n"
                               "hw_mode=g\nchannel=6\nwmm_enabled=1\nauth_algs=1\nwpa=2\n"
                               "wpa_key_mgmt=WPA-PSK\nrsn_pairwise=CCMP\nwpa_passphrase=" + password + "\n")
        os.chmod(str(hostapd), 0o600)
        password = next(line.split("=", 1)[1] for line in hostapd.read_text().splitlines()
                        if line.startswith("wpa_passphrase="))
        dhcpcd = Path("/etc/dhcpcd.conf")
        original = dhcpcd.read_text()
        if "# BEGIN MOTORPI MOBILE" not in original:
            backup = config_dir / "dhcpcd.conf.before-mobile"
            if not backup.exists():
                backup.write_text(original)
            dhcpcd.write_text(original + "\n# BEGIN MOTORPI MOBILE\ninterface wlan0\n"
                               "static ip_address=10.42.0.1/24\nnohook wpa_supplicant\n# END MOTORPI MOBILE\n")
        (config_dir / "dnsmasq.conf").write_text(
            "interface=wlan0\nbind-interfaces\nno-resolv\nno-hosts\n"
            "dhcp-range=10.42.0.10,10.42.0.100,255.255.255.0,12h\n"
            "dhcp-option=3\ndhcp-option=6,10.42.0.1\naddress=/motorpi.local/10.42.0.1\n")
        (Path("/etc/systemd/system") / "motorpi-ap.service").write_text(
            "[Unit]\nDescription=MotorPi dedicated WLAN access point\nAfter=network.target\n"
            "[Service]\nType=simple\nExecStartPre=/sbin/ip link set wlan0 up\n"
            "ExecStartPre=/sbin/ip address replace 10.42.0.1/24 dev wlan0\n"
            "ExecStart=/usr/sbin/hostapd /etc/motorpi-mobile/hostapd.conf\n"
            "Restart=on-failure\nRestartSec=3\n[Install]\nWantedBy=multi-user.target\n")
        (Path("/etc/systemd/system") / "motorpi-dhcp.service").write_text(
            "[Unit]\nDescription=MotorPi WLAN DHCP and local DNS\nAfter=motorpi-ap.service\nRequires=motorpi-ap.service\n"
            "[Service]\nType=simple\nExecStart=/usr/sbin/dnsmasq --keep-in-foreground --conf-file=/etc/motorpi-mobile/dnsmasq.conf\n"
            "Restart=on-failure\nRestartSec=3\n[Install]\nWantedBy=multi-user.target\n")
        # These were freshly installed for this feature; dedicated units keep their scope on wlan0.
        run("systemctl", "disable", "--now", "dnsmasq.service")
        run("systemctl", "stop", "wpa_supplicant@wlan0.service")
    # Keep already provisioned WLAN credentials when updating just the access code.
    hostapd = config_dir / "hostapd.conf"
    if hostapd.exists():
        password = next(line.split("=", 1)[1] for line in hostapd.read_text().splitlines()
                        if line.startswith("wpa_passphrase="))
        credentials += "Wi-Fi SSID: MotorPi\nWi-Fi password: " + password + "\nPi access-point IP: 10.42.0.1\n"
        credentials += "App control: TCP 10.42.0.1:" + str(config.get("listen_port", 8765)) + "\n"
        credentials += "App logs (read-only, same access code): HTTP 10.42.0.1:8081\n"
    if args.app_download:
        download = source / "download"
        if not (download / "motorpi.apk").is_file():
            raise RuntimeError("Copy the APK to mobile/download/motorpi.apk first")
        page = (source / "download.html").read_text(encoding="utf-8")
        version = (download / "version.txt").read_text().strip() if (download / "version.txt").exists() else "unbekannt"
        (download / "index.html").write_text(page.replace("{{VERSION}}", version), encoding="utf-8")
        shutil.copyfile(str(source / "motorpi-download.service"), "/etc/systemd/system/motorpi-download.service")
        credentials += "App download via WLAN: http://10.42.0.1:8080/\n"
    access.write_text(credentials); os.chmod(str(access), 0o600); os.chown(str(access), pi.pw_uid, pi.pw_gid)
    run("systemctl", "daemon-reload")
    run("systemctl", "enable", "--now", "motorpi-mobile.service")
    run("systemctl", "restart", "motorpi-mobile.service")
    # Read-only and a separate process: safe next to a live driving session too.
    run("systemctl", "enable", "--now", "motorpi-logs.service")
    run("systemctl", "restart", "motorpi-logs.service")
    if args.access_point:
        run("systemctl", "enable", "--now", "motorpi-ap.service", "motorpi-dhcp.service")
    if args.app_download:
        run("systemctl", "enable", "--now", "motorpi-download.service")
    print("Installed in simulation mode. Credentials: " + str(access))


if __name__ == "__main__":
    main()
