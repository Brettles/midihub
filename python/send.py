#!/usr/bin/python3

from pymidi import server
from pymidi import packets
import pymidi
import logging
import copy
import time
import select

remoteAddresses = []

def sendPacket(command, remoteAddr):
    channel = 0

    packet = packets.MIDIPacket.create(
        header={
            'rtp_header': {
                'flags': {
                    'v': 0x2,
                    'p': 0,
                    'x': 0,
                    'cc': 0,
                    'm': 0x1,
                    'pt': 0x61
                },
                'sequence_number': ord('K')
            },
            'timestamp': int(time.time()),
            'ssrc': outputSocket.ssrc
        },
        command={
            'flags': {
                'b': 0,
                'j': 0,
                'z': 0,
                'p': 0,
                'len': 3,
            },
            'midi_list': [
                {
                    'delta_time': 0,
                    '__next': 0x80,
                    'command': 'note_on' if command == packets.COMMAND_NOTE_ON else 'note_off',
                    'command_byte': command | (channel & 0xF),
                    'channel': channel,
                    'params': {
                        'key': 'B6',
                        'velocity': 80,
                    }
                }
            ]
        },
        journal='',
    )

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

    def on_midi_commands(self, peer, commandList, journal):
        print(f'{peer.name} sent {commandList[0].command}')

def nonBusyLoop(server, timeout=None):
    sockets = server.socket_map.keys()
    rr, _, _ = select.select(sockets, [], [], timeout)
    for s in rr:
        buffer, addr = s.recvfrom(1024)
        buffer = bytes(buffer)
        proto = server.socket_map[s]
        proto.handle_message(buffer, addr)

logging.basicConfig()
logger = logging.getLogger()
logger.setLevel(logging.INFO)

myServer = server.Server([('0.0.0.0', 5004)])
myServer.add_handler(MyHandler())

myServer._init_protocols()
for socket in myServer.socket_map:
    if type(myServer.socket_map[socket]) is pymidi.protocol.DataProtocol:
        outputSocket = myServer.socket_map[socket]

while True:
    nonBusyLoop(myServer, timeout=0.1)
    if len(remoteAddresses):
        sendPacket(packets.COMMAND_NOTE_ON, remoteAddresses[0])
        time.sleep(0.05)
        sendPacket(packets.COMMAND_NOTE_OFF, remoteAddresses[0])
