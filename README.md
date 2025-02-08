# TEMA 1 - SWITCH

For this project I have followed the instructions from the RL course material to implement a switch for LANs, that supports simple message forwarding, VLAN separation and also the Spanning Tree Protocol. For testing the actual functionality, a Mininet topology was used, based on 3 switches and 6 hosts:

```
h0             h2
  \           /
   S0 - - - S1
  /  \    /   \
h1     S2      h3
      /  \
    h4    h5
```

For each functionality, my implementation was as follows:

## SIMPLE FORWARDING

For this, I have followed the pseudocode given in the course. For each packet received on an interface, the switch will check the destination MAC type:
1. *unicast*: The switch checks if the destination MAC is in the local MAC table, if so it will send the packet to the specific port. Otherwise, the packet is broadcasted to every port, except the source.
2. *multicast*: The packet is being broadcast

## VLAN separation

In order to separate the ports in different VLANs, the ***config*** file of the specific switch was read and the interface names were converted to there omologous port numbers, to ease classification. For the separation to truly work, every packet coming from a host (raw) will have a **VLAN Tag** added, specifying the VLAN of the interface in which it was received, and then forwarded. For the destination host, the switch removes the tag from the packet.

This mechanism is used because the idea of a VLAN is local to the switch and tagged frames are sent only through trunk ports (switch to switch links) and the hosts should not know or care about their status.

After the packet was correctly tagged, it can be sent to any trunk port (trunks are not VLAN specific) or to any host interface with the specified VLAN from the packet's tag. If a destination does not respect this, the switch throws the packet. The implementaton mainly targets the forwarding mechanism and adds verifications for all types of connections **(T to T, h to T, and T to h)**.

## Spanning Tree Protocol

This protocol is used to avoid loops in our network. It looks to set a switch as root and send a specific BPDU packet every second to check for topology changes. Every switch that doesn't have root status, closes all ports, except root ports, to avoid loops. Initially, all switches are considered root and start sending packets.

The implementation strongly took to the pseudocode offered by the course and it works in 2 phases:

### 1. Sending

If a switch is root, it will construct a BPDU packet containing:
- root bridge ID
- sender bridge ID
- root path cost

They are built into an ethernet frame with the `build_bdpu_ether()` function and sent every second to all trunk ports (hosts cannot cause loops, so we will only focus on switches).

### 2. Receiving

For the switch to destinguish between normal packets and BPDU, the destination MAC is checked for the BPDU-specific multicast address: **01:80:c2:00:00:00**. If so, all the tagging logic is skipped and forwarding will be done only in specific situations.

For the BPDU packet, we need to take into account a few situations and act accordingly:
- Priority of packet is lower than that of switch: The switch loses root status and adds 10 to the cost of the root distance. All non-root ports are closed and a new BPDU frame is sent containing the new root bridge ID and updated cost.
- Priority of packet is equal to that of switch: The switch is root and the packet will only be used to check if we found a shorter path. If the path isn't shorter, we can still set non-entrance ports to designated, as we are in a root switch.
- Packet sender is the switch, but not root: Ports are closed.

This strategy will prevent bandwidth pollution caused by loops in the network. The only modification brought to the forwarding of normal packets is that Trunk forwarding will have to check if the given port is in listening state.