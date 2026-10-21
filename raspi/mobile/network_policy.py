"""Who may talk to the mobile services: only the MotorPi WLAN (plus loopback).

There is no access code; joining the WPA2-protected MotorPi WLAN is the
admission. The services also listen on Ethernet/the home LAN, so the peer
address is what keeps those out. Python 3.7 compatible, standard library only.
"""
import ipaddress

DEFAULT_NETWORKS = ("10.42.0.0/24", "127.0.0.0/8")
REJECTION = "Only reachable from the MotorPi WLAN"


def parse_networks(networks=None):
    return [ipaddress.ip_network(net) for net in (networks or DEFAULT_NETWORKS)]


def allowed(address, networks):
    try:
        peer = ipaddress.ip_address(address)
    except ValueError:
        return False
    # An IPv4 client on a dual-stack socket shows up as ::ffff:a.b.c.d.
    if peer.version == 6 and peer.ipv4_mapped is not None:
        peer = peer.ipv4_mapped
    return any(peer in network for network in networks)
