"""Which addresses may use a key. A rule is a CIDR (`10.0.0.0/8`, `203.0.113.7`) or `@server`,
meaning this machine: loopback plus the addresses the machine itself owns, found automatically."""

import ipaddress
import socket
from typing import Callable, Iterable, Optional, Set, Union

Address = Union[ipaddress.IPv4Address, ipaddress.IPv6Address]
SERVER = "@server"


def parse(text: str) -> Optional[Address]:
    try:
        address = ipaddress.ip_address(text.split("%", 1)[0])
    except ValueError:
        return None
    mapped = getattr(address, "ipv4_mapped", None)
    return mapped or address


def own_addresses(extra: Iterable[str] = ()) -> Set[Address]:
    """The machine's own addresses: its host name, its default-route source (no packet is sent),
    plus any configured extras."""
    found: Set[Address] = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None):
            address = parse(str(info[4][0]))
            if address:
                found.add(address)
    except OSError:
        pass
    for family, probe in ((socket.AF_INET, "192.0.2.1"), (socket.AF_INET6, "2001:db8::1")):
        try:
            with socket.socket(family, socket.SOCK_DGRAM) as sock:
                sock.connect((probe, 9))  # picks the outgoing interface; sends nothing
                address = parse(str(sock.getsockname()[0]))
                if address:
                    found.add(address)
        except OSError:
            continue
    for text in extra:
        address = parse(text)
        if address:
            found.add(address)
    return found


def allowed(
    client_ip: Optional[str], rules: Iterable[str], own: Callable[[], Set[Address]]
) -> bool:
    """True when there are no rules, or the address matches one of them."""
    rules = list(rules)
    if not rules:
        return True
    address = parse(client_ip or "")
    if address is None:
        return False
    for rule in rules:
        if rule == SERVER:
            if address.is_loopback or address in own():
                return True
            continue
        try:
            if address in ipaddress.ip_network(rule, strict=False):
                return True
        except ValueError:
            continue
    return False
