#!/usr/bin/python3

from pymidi import server
from pymidi import packets
from pymidi.utils import get_timestamp
import pymidi
import logging
import copy
import time
import sys

remoteAddresses = []
sequenceNumber = 0

logging.basicConfig()
logger = logging.getLogger()
logger.setLevel(logging.INFO)

def sendPacket(midiPacket, remoteAddr):
    global sequenceNumber

    length = 3+4*(len(midiPacket.command.midi_list)-1) if len(midiPacket.command.midi_list) else 0

    try:
        packet = packets.MIDIPacket.create(
            header={
                'rtp_header': {
                    'flags': {
                        'v': midiPacket.header.rtp_header.flags.v,
                        'p': midiPacket.header.rtp_header.flags.p,
                        'x': midiPacket.header.rtp_header.flags.x,
                        'cc': midiPacket.header.rtp_header.flags.cc,
                        'm': midiPacket.header.rtp_header.flags.m,
                        'pt': 0x61
                    },
                    'sequence_number': sequenceNumber
                },
                'timestamp': get_timestamp(),
                'ssrc': outputSocket.ssrc
            },
            command={
                'flags': {
                    'b': midiPacket.command.flags.b,
                    'j': midiPacket.command.flags.j,
                    'z': midiPacket.command.flags.z,
                    'p': midiPacket.command.flags.p,
                    'len': length
                },
                'midi_list': midiPacket.command.midi_list,
            },
            journal = midiPacket.journal
        )
    except Exception as e:
        print(f'---> {e}')
        print(midiPacket)
    else:
        outputSocket.sendto(packet, remoteAddr)

class MyHandler(server.Handler):
    def on_peer_connected(self, peer):
        dataAddress = (peer.addr[0], peer.addr[1]+1)
        if dataAddress not in remoteAddresses:
            remoteAddresses.append(dataAddress)
        print('Peer connected: {}'.format(peer))

    def on_peer_disconnected(self, peer):
        dataAddress = (peer.addr[0], peer.addr[1]+1)
        if dataAddress in remoteAddresses:
            remoteAddresses.remove(dataAddress)
        print('Peer disconnected: {}'.format(peer))

    def on_midi_commands(self, peer, midi_packet):
        global sequenceNumber

        tempAddresses = copy.copy(remoteAddresses)
        tempAddresses.remove(peer.addr)

        if not len(tempAddresses): return

        print(f'{peer.name} sent {midi_packet.command.midi_list[0].command} - forwarding to {tempAddresses}')
        for remote in tempAddresses:
            sendPacket(midi_packet, remote)

        sequenceNumber += len(midi_packet.command.midi_list)

myServer = server.Server([('0.0.0.0', 5040)])
myServer.add_handler(MyHandler())

myServer._init_protocols()
for socket in myServer.socket_map:
    if type(myServer.socket_map[socket]) is pymidi.protocol.DataProtocol:
        outputSocket = myServer.socket_map[socket]

while True:
    myServer._loop_once()
