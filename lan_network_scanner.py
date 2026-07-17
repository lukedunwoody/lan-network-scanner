# region Imports and Constants

import subprocess
import socket
import re
import ipaddress
import time
import webbrowser
import random
from concurrent.futures import ThreadPoolExecutor, as_completed

import progress_bar

import psutil
import pyperclip

MAX_WORKERS = 20
PORT_LIST = [22, 80, 443, 139, 445, 3389, 5900, 8080, 8443, 21, 23, 25, 53, 110, 123, 135, 137, 138, 161, 5353]
NAMES = ["ScanYe West", "The Ping Lebowski", "Pingenator 3000", "Mr. StealYoIP", "CatchMeIPYouCan"]
HELP = """
Available Commands:
────────────────────────────────────────────
myinfo
    Show your local network info (IP and subnet mask).

scan prefix <x.y.z>
    Scan all 254 hosts within the given prefix (x.y.z).

scan range <x.y.z> <x.y.w>
    Scan multiple /24 prefixes in sequence.

scan auto
    Automatically detect your local subnet and scan it.

rescan
    Repeat the most recent scan command.

list
    Show all discovered devices with IP, MAC, hostname, and open ports.

info <ip>
    Show detailed information for a specific device.

ping <ip>
    Ping a device and show its response time.

wake <ip>
    Send a Wake-on-LAN packet to a device (if supported).

open <ip>
    Open the web interface for a device in your browser.

copy <ip>
    Copy a device's IP address to the clipboard.

test <ip> <port>
    Test if a specific port is open on a device.

help
    Show this help message.

quit
    Exit the program.
────────────────────────────────────────────
"""

#endregion

#region Errors

# Print Helper Function
def error(msg):
    print(f"\033[31m[✗] {msg}\033[0m") # red
def info(msg):
    print(f"\033[36m[i] {msg}\033[0m")  # cyan
def success(msg):
    print(f"\033[32m[✓] {msg}\033[0m")  # green
def fail(msg):
    print(f"\033[33m[!] {msg}\033[0m")  # orange

# Error Messages
ERR_INVALID_MAC = "MAC address must be 12 hex digits."
ERR_INVALID_PORT = "Not a valid port."
ERR_INVALID_CMD = "Invalid command. Have you tried getting hel- sorry, I meant using 'help'?"

ERR_NO_ADMIN = "You need admin/root privileges to perform this action."
ERR_NO_LOCAL = "Could not determine local IP."
ERR_NO_SUBNET = "Could not determine local subnet."
ERR_NO_NETMASK = "Could not determine subnet mask for target IP"
ERR_NO_RESCAN = "No previous scan found."
ERR_NO_LIST = "No Device List found. Have you ran 'scan'?"
ERR_NO_IP_OR_LIST = "Couldn't find ip and/or current device list. Did you enter the ip correctly? Have you tried running 'scan'?"

#endregion

#region Helper Functions

def safe_get(seq, index, default=None):
    return seq[index] if len(seq) > index else default

def get_column_max_lengths(table):
    if not table:
        return {}

    # Start by getting all field names from the first entry
    field_names = table[0].keys()
    max_lengths = {field: len(str(field)) for field in field_names}  # Include header length

    for row in table:
        for field in field_names:
            value = str(row.get(field, ""))
            max_lengths[field] = max(max_lengths[field], len(value))

    return max_lengths

def run_parallel(task_fn, items, max_workers=MAX_WORKERS, progress_msg=None):
    items = list(items)
    total = len(items)

    if progress_msg:
        progress_bar.prepare(total, message=progress_msg)

    start_time = time.time()
    last_time = time.time()
    completed = 0

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(task_fn, item) for item in items]

        for future in as_completed(futures):
            _ = future.result()

            completed += 1
            if progress_msg:
                progress_bar.update(completed, total, last_time, message=progress_msg)
            last_time = time.time()

    if progress_msg:
        progress_bar.finish(total, start_time, message=progress_msg)

def run_parallel_and_record(task_fn, items, table_output, max_workers=MAX_WORKERS, progress_msg=None):
    items = list(items)
    total = len(items)
    results = [None] * len(items)

    if progress_msg:
        progress_bar.prepare(total, message=progress_msg)

    start_time = time.time()
    last_time = time.time()
    completed = 0

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_idx = {executor.submit(task_fn, items[i]): i for i in range(total)}

        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            try:
                result = future.result()
                results[idx] = result
            except Exception as e:
                result = f"Error: {e}"
                results[idx] = None

            # Record into external table
            table_output.append(result)

            completed += 1
            if progress_msg:
                progress_bar.update(completed, total, last_time, message=progress_msg)
            last_time = time.time()

    if progress_msg:
        progress_bar.finish(total, start_time, message=progress_msg)

    return results

#endregion

#region Essential Functions

# Get your IPv4
def get_local_ip_and_mask():
    for iface, addrs in psutil.net_if_addrs().items():
        for addr in addrs:
            if addr.family == socket.AF_INET:  # IPv4
                return addr.address, addr.netmask
    return None, None

# Ping a Host, Return in s Response Time
def ping_ip(host, count=1, timeout=100):
    start_time = time.time()
    result = subprocess.run(
        ["ping", "-n", str(count), "-w", str(timeout), str(host)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )

    # On Windows, returncode == 0 means the ping was successful
    if result.returncode == 0:
        return time.time() - start_time
    else:
        return None

# Auto Scan Pings
def ping_prefix(prefix):
    hosts = [f"{prefix}.{i}" for i in range(1, 256)]
    run_parallel(ping_ip, hosts, progress_msg="Pinging hosts")

# Manual Scan Pings, "x.y.z" (required). end: "x.y.w" (optional; x.y must match).
def ping_prefix_range(start, end = None) -> None:
    def _parse3(p: str):
        parts = p.split('.')
        if len(parts) != 3:
            raise ValueError("Prefix must be in x.y.z form.")
        a, b, c = (int(x) for x in parts)  # may raise ValueError
        if not all(0 <= v <= 255 for v in (a, b, c)):
            raise ValueError("Octets must be 0..255.")
        return a, b, c

    a1, b1, z1 = _parse3(start)
    if end is None:
        z_start, z_end = z1, z1
    else:
        a2, b2, z2 = _parse3(end)
        if (a1, b1) != (a2, b2):
            raise ValueError("Start and end must share the same first two octets (x.y).")
        z_start, z_end = min(z1, z2), max(z1, z2)

    prefixes = [f"{a1}.{b1}.{z}" for z in range(z_start, z_end + 1)]
    hosts = [f"{p}.{i}" for p in prefixes for i in range(1, 256)]
    run_parallel(ping_ip, hosts, progress_msg="Pinging hosts")

# Prefix Scan Pings
def ping_subnet(ip, netmask):
    network = ipaddress.IPv4Network(f"{ip}/{netmask}", strict=False)
    hosts = network.hosts()
    run_parallel(ping_ip, hosts, progress_msg="Pinging hosts")

# Get the Arp Table and Format in a List for Printing
def get_arp_table(include_static=False):
    try:
        arp_output = subprocess.check_output("arp -a", shell=True, text=True)
    except PermissionError:
        print(ERR_NO_ADMIN)
        return
    arp_table = []
    index = 0
    for line in arp_output.splitlines():
        m = re.match(r"\s*(\d+\.\d+\.\d+\.\d+)\s+([0-9a-f-]+)\s+(\w+)", line, re.I)
        if m:
            ip, mac, type_ = m.groups()
            if include_static or type_ == "dynamic":
                arp_table.append((index, ip, mac))
                index += 1
    return arp_table

#endregion

#region Essential Functions Pt 2

def resolve_hostname(ip):
    try:
        name, _, _ = socket.gethostbyaddr(ip)
        return name
    except Exception:
        return "n/a"

def scan_ports(ip, ports=PORT_LIST):
    open_ports = []
    for port in ports:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(0.5)  # short timeout
            result = sock.connect_ex((ip, port))
            if result == 0:
                open_ports.append(port)
            sock.close()
        except Exception:
            pass
    return open_ports

def complete_arp_entry(entry):
    index, ip, mac = entry
    hostname = resolve_hostname(ip)
    ports = scan_ports(ip)
    return index, ip, mac, hostname, ports

# Returns a Complete Device List with Everything Resolved
def complete_device_list(arp_entries):
    results = []
    run_parallel_and_record(complete_arp_entry, arp_entries, results, progress_msg="Completing arp entries")

    # Filter out None results (failed scans)
    results = [r for r in results if r]
    # Sort strictly by the index assigned in get_arp_table
    results.sort(key=lambda r: r[0])

    devices = []
    for index, ip, mac, hostname, ports in results:
        devices.append({
            "ip": ip,
            "mac": mac,
            "hostname": hostname,
            "open_ports": ports,
            "print_ports": ", ".join(map(str, ports)) if ports else "n/a"
        })

    return devices

# Prints a List that Looks Nice :)
def print_device_list(devices):
    max_lengths = get_column_max_lengths(devices)
    print(f"{"IP":<{max_lengths['ip']+4}}{"Mac Address":<{max_lengths['mac']+4}}{"Hostname":<{max_lengths['hostname']+4}}{"Ports":<{max_lengths['print_ports']+4}}")
    for d in devices:
        print(f"{d['ip']:<{max_lengths['ip']+4}}{d['mac']:<{max_lengths['mac']+4}}{d['hostname']:<{max_lengths['hostname']+4}}{d['print_ports']:<{max_lengths['print_ports']+4}}")

#endregion

#region Right Click Functions

# Helper for everything
def find_device_by_ip(devices, target_ip):
    for device in devices:
        if device.get("ip") == target_ip:
            return device  # return the dict immediately
    error(ERR_NO_IP_OR_LIST)
    return None  # if not found

# In CLI
def show_info(devices, ip):
    dev = find_device_by_ip(devices, ip)
    if dev:
        print(f"IP: {dev['ip']}, MAC: {dev['mac']}, Name: {dev['hostname']}, Ports: {dev['print_ports']}")

# In CLI
def ping_output(ip):
    info(f"Pinging {ip}")
    response_time = ping_ip(ip)
    if response_time:
        success(f"{ip} responded in {round(response_time * 1000)} ms")
    else:
        fail(f"{ip} did not respond")

# In CLI
def open_web_ui_for(ip):
    ports = scan_ports(ip, [443, 8443, 80, 8080])

    if ports:
        # prefer https (443, 8443), then http (80,8080)
        preferred = [443, 8443, 80, 8080]
        for p in preferred:
            if p in ports:
                scheme = "https" if p in (443, 8443) else "http"
                webbrowser.open(f"{scheme}://{ip}:{p}")
                return
        # fallback to first port
        webbrowser.open(f"http://{ip}:{ports[0]}")
        return

    # no ports known: try https then http default ports
    if webbrowser.open(f"https://{ip}"):
        return
    webbrowser.open(f"http://{ip}")

# In CLI
def find_subnet_mask_for_ip(ip):
    target = ipaddress.IPv4Address(ip)
    for iface, addrs in psutil.net_if_addrs().items():
        for addr in addrs:
            if addr.family.name == "AF_INET":
                try:
                    net = ipaddress.IPv4Network(f"{addr.address}/{addr.netmask}", strict=False)
                    if target in net:
                        return addr.netmask
                except Exception:
                    continue
    return None

def send_magic_packet(ip_address, current_list, port=9):
    device_info = find_device_by_ip(current_list, ip_address)
    if device_info:
        mac_address = device_info['mac']
    else:
        return

    netmask = find_subnet_mask_for_ip(ip_address)
    if not netmask:
        error(ERR_NO_NETMASK)
        return
    broadcast = ipaddress.IPv4Network(f"{ip_address}/{netmask}", strict=False).broadcast_address

    # Clean MAC address
    mac_address_clean = mac_address.replace(":", "").replace("-", "").lower()

    if len(mac_address_clean) != 12:
        error(ERR_INVALID_MAC)
        return

    # Build magic packet (6x FF + 16x MAC)
    data = bytes.fromhex("FF" * 6 + mac_address_clean * 16)

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            s.sendto(data, (str(broadcast), port))
        info(f"Magic packet sent to {mac_address.upper()} via {broadcast}:{port}")
    except PermissionError:
        error(ERR_NO_ADMIN)
    except OSError as e:
        error(e)

# In CLI
def copy_info(devices, ip):
    dev = find_device_by_ip(devices, ip)
    if dev:
        text = f"IP: {dev['ip']}, MAC: {dev['mac']}, Name: {dev['hostname']}, Ports: {dev['print_ports']}"
        pyperclip.copy(text)
        info(f"Copied info for {ip} to clipboard!")
    else:
        error(ERR_NO_IP_OR_LIST)

# In CLI
def test_port(ip, port, timeout=0.5):
    start = time.time()
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        if sock.connect_ex((ip, port)) == 0:
            response_time = round((time.time() - start) * 1000)
            sock.close()
            return True, response_time
        sock.close()
        return False, None
    except Exception:
        return False, None

def test_port_output(ip, port, timeout=0.5):
    try:
        port = int(port)
    except ValueError:
        error(ERR_INVALID_PORT)
        return

    if not (0 < port < 65536):
        error(ERR_INVALID_PORT)
        return

    info(f"Testing port {port} on {ip}")
    result, response_time = test_port(ip, port)
    if result and response_time:
        success(f"Port {port} on {ip} responded in {response_time}ms")
    else:
        fail(f"Port {port} on {ip} did not respond in time")

#endregion

#region Main

def main():
    print(f"{random.choice(NAMES)} ready to scan your network.\n(Type 'help' for commands.)")
    current_devices = None
    last_scan_args = [None, None, None]

    while True:
        cmd = input("> ").strip().lower()
        if not cmd:
            print("Please enter a command.")
            continue
        elif cmd in ("quit", "exit", "q"):
            return

        parts = cmd.split()

        if parts[0] in ("help", "h"):
            print(HELP)

        elif parts[0] == "myinfo":
            local_ip, netmask = get_local_ip_and_mask()
            if not local_ip:
                error(ERR_NO_LOCAL)
                return
            success(f"Local IP: {local_ip}, Subnet Mask: {netmask}")

        elif parts[0] == "scan":
            if len(parts) < 2:
                fail("Usage: scan <prefix|range|auto> [args]")
                continue
            if safe_get(parts, 1) == "range":
                range_start = safe_get(parts, 2)
                range_end = safe_get(parts, 3)
                ping_prefix_range(range_start, range_end)
                last_scan_args = [safe_get(parts, 1), range_start, range_end]
            elif safe_get(parts, 1) == "prefix":
                prefix = safe_get(parts, 2)
                ping_prefix(prefix)
                last_scan_args = [safe_get(parts, 1), prefix, None]
            else:
                local_ip, netmask = get_local_ip_and_mask()
                if not local_ip:
                    error(ERR_NO_SUBNET)
                    continue
                ping_subnet(local_ip, netmask)
                last_scan_args = [safe_get(parts, 1), None, None]
            current_devices = complete_device_list(get_arp_table(include_static=False))

        elif parts[0] == "rescan":
            if not last_scan_args[0]:
                error(ERR_NO_RESCAN)
                continue
            elif last_scan_args[0] == "range":
                range_start = last_scan_args[1]
                range_end = last_scan_args[2]
                ping_prefix_range(range_start, range_end)
            elif last_scan_args[0] == "prefix":
                prefix = last_scan_args[1]
                ping_prefix(prefix)
            else:
                local_ip, netmask = get_local_ip_and_mask()
                if not local_ip:
                    error(ERR_NO_SUBNET)
                    continue
                ping_subnet(local_ip, netmask)
            current_devices = complete_device_list(get_arp_table(include_static=False))

        elif parts[0] == "list":
            if current_devices:
                print_device_list(current_devices)
            else:
                error(ERR_NO_LIST)

        elif parts[0] == "info":
            ip = safe_get(parts, 1)
            if ip and current_devices:
                show_info(current_devices, ip)
            else:
                error(ERR_NO_IP_OR_LIST)

        elif parts[0] == "ping":
            ping_output(safe_get(parts, 1))

        elif parts[0] == "wake":
            send_magic_packet(safe_get(parts, 1), current_devices)

        elif parts[0] == "open":
            open_web_ui_for(safe_get(parts, 1))

        elif parts[0] == "copy":
            ip = safe_get(parts, 1)
            if ip and current_devices:
                copy_info(current_devices, ip)
            else:
                error(ERR_NO_IP_OR_LIST)

        elif parts[0] == "test":
            test_port_output(safe_get(parts, 1), safe_get(parts, 2))

        else:
            error(ERR_INVALID_CMD)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        info("Interrupted by user. Exiting cleanly...")
        time.sleep(0.3)

#endregion
