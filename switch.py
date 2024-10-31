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

def send_bdpu_every_sec():
    while True:
        # TODO Send BDPU every second if necessary
        time.sleep(1)

def is_unicast(addr):
    
    # check if least significant bit of most significant Byte is 0
    return (addr[0] & 1) == 0

def parse_vlan_data(interfaces, path):
    priority = -1
    VLAN_table = {}

    # Read vlan data from config file
    with open(path, "r") as f:
        priority = int(f.readline().strip())

        for line in f:
            name = line.strip().split(' ')
            VLAN_table[name[0]] = int(name[1]) if name[1] != 'T' else 'T'
    
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

    # print("# Starting switch with id {}".format(switch_id), flush=True)
    # print("[INFO] Switch MAC", ':'.join(f'{b:02x}' for b in get_switch_mac()))

    # Create and start a new thread that deals with sending BDPU
    t = threading.Thread(target=send_bdpu_every_sec)
    t.start()

    # Printing interface names
    # for i in interfaces:
    #     print(get_interface_name(i))

    priority, VLAN_table = parse_vlan_data(interfaces, f"configs/switch{switch_id}.cfg")
    
    
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

        # print(f'Destination MAC: {dest_mac}')
        # print(f'Source MAC: {src_mac}')
        # print(f'EtherType: {ethertype}')

        # print("Received frame of size {} on interface {}".format(length, interface), flush=True)

        if vlan_id == -1:
            vlan_id = VLAN_table[interface]
            tagged = data[0:12] + create_vlan_tag(vlan_id) + data[12:]
            length += 4

        # TODO: Implement forwarding with learning
        if src_mac not in MAC_table:
            MAC_table[src_mac] = interface

        if is_unicast(dest_mac_byte) and dest_mac in MAC_table:
            if VLAN_table[MAC_table[dest_mac]] == 'T':
                send_to_link(MAC_table[dest_mac], length, tagged)
            elif VLAN_table[MAC_table[dest_mac]] == vlan_id:
                untagged = tagged[0:12] + tagged[16:]
                send_to_link(MAC_table[dest_mac], length-4, untagged)
        else:
            for i in interfaces:
                if i != interface:
                    if VLAN_table[i] == 'T':
                        send_to_link(i, length, tagged)
                    elif VLAN_table[i] == vlan_id:
                        untagged = tagged[0:12] + tagged[16:]
                        send_to_link(i, length-4, untagged)

        # TODO: Implement VLAN support
        # TODO: Implement STP support

        # data is of type bytes.
        # send_to_link(i, length, data)

if __name__ == "__main__":
    main()
