#!/usr/bin/python3
import sys
import struct
import wrapper
import threading
import time
from wrapper import recv_from_any_link, send_to_link, get_switch_mac, get_interface_name

def parse_ethernet_header(data):
    # Unpack the header fields from the byte array
    #dest_mac, src_mac, ethertype = struct.unpack('!6s6sH', data[:14])
    dest_mac = data[0:6]
    src_mac = data[6:12]
    
    # Extract ethertype. Under 802.1Q, this may be the bytes from the VLAN TAG
    ether_type = (data[12] << 8) + data[13]

    vlan_id = -1
    # Check for VLAN tag (0x8100 in network byte order is b'\x81\x00')
    if ether_type == 0x8200:
        vlan_tci = int.from_bytes(data[14:16], byteorder='big')
        vlan_id = vlan_tci & 0x0FFF  # extract the 12-bit VLAN ID
        ether_type = (data[16] << 8) + data[17]

    return dest_mac, src_mac, ether_type, vlan_id

def create_vlan_tag(vlan_id):
    # 0x8100 for the Ethertype for 802.1Q
    # vlan_id & 0x0FFF ensures that only the last 12 bits are used
    return struct.pack('!H', 0x8200) + struct.pack('!H', vlan_id & 0x0FFF)

def build_bdpu_ether(root, sender, cost):
    src_mac = get_switch_mac()
    dest_mac = bytes([0x01, 0x80, 0xC2, 0x00, 0x00, 0x00])

    ether_type = bytes([0x42, 0x00])

    # We will build a custom BPDU header for simplicity
    root_bridge_ID = int.to_bytes(root, 2, byteorder='big')
    sender_bridge_ID = int.to_bytes(sender, 2, byteorder='big')
    sender_path_cost = int.to_bytes(cost, 4, byteorder='big')

    bpdu_header = root_bridge_ID + sender_bridge_ID + sender_path_cost

    bpdu = dest_mac + src_mac + ether_type + bpdu_header

    return bpdu

def send_bdpu_every_sec(is_root, interfaces, bridge_ID, VLAN_table):
    while True:
        # Send BDPU every second on all trunks
        if is_root:
            bpdu = build_bdpu_ether(bridge_ID, bridge_ID, 0)

            for i in interfaces:
                if VLAN_table[i] == 'T':
                    send_to_link(i, len(bpdu), bpdu)

        time.sleep(1)

def is_unicast(addr):
    
    # check if least significant bit of most significant Byte is 0
    return (addr[0] & 1) == 0

def read_switch_config(switch_id, interfaces):

    VLAN_table = {}
    # Read vlan data from config file
    with open(f"configs/switch{switch_id}.cfg", "r") as f:
        priority = int(f.readline().strip())

        for line in f:
            name, vlan = line.strip().split(' ')
            VLAN_table[name] = int(vlan) if vlan != 'T' else 'T'
    
    new_table = {}
    # Associate interface to VLAN
    for i in interfaces:
        new_table[i] = VLAN_table[get_interface_name(i)]
    
    return priority, new_table

def main():
    # init returns the max interface number. Our interfaces
    # are 0, 1, 2, ..., init_ret value + 1
    switch_id = sys.argv[1]

    num_interfaces = wrapper.init(sys.argv[2:])
    interfaces = range(0, num_interfaces)
    is_root = True

    print("# Starting switch with id {}".format(switch_id), flush=True)
    print("[INFO] Switch MAC", ':'.join(f'{b:02x}' for b in get_switch_mac()))

    priority, VLAN_table = read_switch_config(switch_id, interfaces)

    port_type = {}
    port_state = {}
    
    own_bridge_ID = priority
    root_bridge_ID = own_bridge_ID
    root_path_cost = 0

    for i in interfaces:
        if VLAN_table[i] == 'T':
            port_type[i] = 'DESIGNATED'
            port_state[i] = 'LISTENING'

    # Create and start a new thread that deals with sending BDPU
    t = threading.Thread(target=send_bdpu_every_sec, args=(is_root, interfaces, own_bridge_ID, VLAN_table))
    t.start()

    # Printing interface names
    for i in interfaces:
        print(get_interface_name(i))
    
    MAC_table = {}

    while True:
        # Note that data is of type bytes([...]).
        # b1 = bytes([72, 101, 108, 108, 111])  # "Hello"
        # b2 = bytes([32, 87, 111, 114, 108, 100])  # " World"
        # b3 = b1[0:2] + b[3:4].
        interface, data, length = recv_from_any_link()

        dest_mac, src_mac, ethertype, vlan_id = parse_ethernet_header(data)

        # save a byte copy of destination for unicast check
        dest_mac_byte = dest_mac

        # Print the MAC src and MAC dst in human readable format
        dest_mac = ':'.join(f'{b:02x}' for b in dest_mac)
        src_mac = ':'.join(f'{b:02x}' for b in src_mac)

        # Note. Adding a VLAN tag can be as easy as
        # tagged_frame = data[0:12] + create_vlan_tag(10) + data[12:]

        print(f'Destination MAC: {dest_mac}')
        print(f'Source MAC: {src_mac}')
        print(f'EtherType: {ethertype}')

        print("Received frame of size {} on interface {}".format(length, interface), flush=True)

        # CHeck if BDPU packet arrived
        if dest_mac == '01:80:c2:00:00:00':

            # Extract relevant data form header
            bpdu_root_bridge = int.from_bytes(data[14:16], byteorder='big')
            bpdu_sender_bridge = int.from_bytes(data[16:18], byteorder = 'big')
            bpdu_cost = int.from_bytes(data[18:], byteorder='big')

            # We found a better match for root
            if bpdu_root_bridge < root_bridge_ID:
                root_bridge_ID = bpdu_root_bridge
                root_path_cost = bpdu_cost + 10
                root_port = interface
                is_root = False

                # Set all trunks to blocking except root port
                if root_bridge_ID != own_bridge_ID:
                    for i in interfaces:
                        if VLAN_table[i] == 'T' and i != root_port:
                            port_state[i] = 'BLOCKING'
                
                if port_state[root_port] == 'BLOCKING':
                    port_state[root_port] = 'LISTENING'
                
                # Resend BPDU with new root metadata
                new_bpdu = build_bdpu_ether(bpdu_root_bridge, own_bridge_ID, root_path_cost)

                for i in interfaces:
                    if VLAN_table[i] == 'T' and i != root_port:
                        send_to_link(i, len(new_bpdu), new_bpdu)
            
            elif bpdu_root_bridge == root_bridge_ID:

                # Check if we found a shorter path to root
                for i in interfaces:
                    if i == interface and bpdu_cost + 10 < root_path_cost:
                        root_path_cost = bpdu_cost + 10

                    # Set i as a designated port
                    elif i != interface and bpdu_cost > root_path_cost:
                        if VLAN_table[i] == 'T' and port_type[i] != 'DESIGNATED':
                            port_type[i], port_state[i] = 'DESIGNATED', 'LISTENING'
            
            # We found a loop so we close all other ports
            elif bpdu_sender_bridge == own_bridge_ID:
                for i in interfaces:
                    if i != interface:
                        port_type[i], port_state[i] = 'BLOCKING', 'BLOCKING'
            
            # Set all trunks to designated if we are root and skip to next iteration
            if own_bridge_ID == root_bridge_ID:
                for i in interfaces:
                    if VLAN_table[i] == 'T':
                        port_type[i], port_state[i] = 'DESIGNATED', 'LISTENING'

            continue

        # Add VLAN tag if missing
        if vlan_id == -1:
            vlan_id = VLAN_table[interface]
            frame = data[0:12] + create_vlan_tag(vlan_id) + data[12:]
            length += 4
        else:
            frame = data


        if src_mac not in MAC_table:
            MAC_table[src_mac] = interface

        # Send to trunk only if listening and to hosts only if correct VLAN id
        if is_unicast(dest_mac_byte) and dest_mac in MAC_table:
            if VLAN_table[MAC_table[dest_mac]] == 'T' and port_state[MAC_table[dest_mac]] == 'LISTENING':
                send_to_link(MAC_table[dest_mac], length, frame)

            elif VLAN_table[MAC_table[dest_mac]] == vlan_id:
                untagged = frame[0:12] + frame[16:]
                send_to_link(MAC_table[dest_mac], length-4, untagged)

        else:
            # Send multicast
            for i in interfaces:
                if i != interface:
                    if VLAN_table[i] == 'T' and port_state[i] == 'LISTENING':
                        send_to_link(i, length, frame)

                    elif VLAN_table[i] == vlan_id:
                        untagged = frame[0:12] + frame[16:]
                        send_to_link(i, length-4, untagged)

if __name__ == "__main__":
    main()
