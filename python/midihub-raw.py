#!/usr/bin/python3

# pip3 install construct

from builtins import bytes

import logging
import select
import socket
import sys
import os
import signal
import json
import boto3

import pymidi.server
from pymidi.protocol import DataProtocol
from pymidi.protocol import ControlProtocol
from pymidi import packets
from pymidi.utils import get_timestamp

logger = None

midiPorts = {'GroupOne': [5140, 5142], 'GroupTwo': [5150, 5152]}
transmitPeers = {}

sqs = boto3.client('sqs')
queueUrl = 'https://sqs.ap-southeast-1.amazonaws.com/995179897743/midihubRaw-SIN'

portRanges = {'Low':range(0, 43), 'Mid':range(43, 86), 'High':range(86, 127), 'All':range(0, 127)}

class midiHandler(pymidi.server.Handler):
    #
    # task = receive | send
    #  A "receive" ports takes midi messages and forwards them to a peer "send"
    #  port while a "send" port does nothing when it receives messages.
    #
    # peerPort = the port we send to if we are the receivce port
    #
    def __init__(self, task, transmitPeer):
        self.logger = logging.getLogger()
        self.task = task
        self.transmitSocket = None
        self.peer = None
        self.sequenceNumber = 10000

        if task == 'receive':
            previousPort = 0
            for socket in transmitPeer.socket_map:
                port = socket.getsockname()[1]
                if port > previousPort:
                    self.transmitSocket = socket
                    print(f'Peer is on port {port}')
                previousPort = port

    def on_peer_connected(self, peer):
        self.peer = peer
        self.logger.info(f'Peer connected: {peer}')

    def on_peer_disconnected(self, peer):
        self.logger.info(f'Peer disconnected: {peer}')

    def on_midi_commands(self, peer, midi_packet):
        if self.task == 'receive':
            for command in midi_packet.command.midi_list:
                print(command)
                sendCommand(self, self.transmitSocket, command)

def sendCommand(handlerInfo, socket, command):
    header = { 'rtp_header': { 'flags': { 'v': 0x2,
                                          'p': 0,
                                          'x': 0,
                                          'cc': 0,
                                          'm': 0x1,
                                          'pt': 0x61
                                        },
                               'sequence_number': handlerInfo.sequenceNumber
                             },
               'timestamp': get_timestamp(),
               'ssrc': handlerInfo.peer.ssrc,
             }

    newcommand = {
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
                    'command': 'note_on',
                    'command_byte': pymidi.packets.COMMAND_NOTE_ON | (0 & 0xF),
                    'channel': 0,
                    'params': {
                        'key': 64,
                        'velocity': 64,
                    },
                }
            ],
        }

    try:
        packet = packets.MIDIPacket.create(header=header, command=newcommand, journal='')
    except Exception as e:
        logger.error(f'Packet create failed: {e}') 
        return

    print(socket)
    print(type(socket))
    try:
        socket.sendto(packet, (handlerInfo.peer.addr[0], handlerInfo.peer.addr[1]+1))
        print('transmitted')
        handlerInfo.sequenceNumber += 1
        print(f'new seq {handlerInfo.sequenceNumber}')
    except Exception as e:
        logger.error(f'sendto failed: {e}') 

def sendNoteOff(socketInfo, note, channel, velocity=0):
    command = { 'flags': { 'b': 0,
                           'j': 0,
                           'z': 0,
                           'p': 0,
                           'len': 3,
                         },
                'midi_list': [ { 'delta_time': 0,
                                 '__next': 0x80,
                                 'command': 'note_off',
                                 'command_byte': pymidi.packets.COMMAND_NOTE_OFF | (channel & 0xF),
                                 'channel': channel,
                                 'params': { 'key': note,
                                             'velocity': velocity,
                                           },
                               } ],
              }

    sendCommand(socketInfo, command)

def main():
    global logger

    signal.signal(signal.SIGINT, interrupted)

    logging.basicConfig()
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    if alreadyRunning():
        logger.debug('This is the second copy - stopping')
        sys.exit(0)

    configure()

    servers = {}
    for group in midiPorts:
        servers[group] = [None, None]

        print(f'Setting up {midiPorts[group][1]}')
        servers[group][1] = pymidi.server.Server.from_bind_addrs([f'0.0.0.0:{midiPorts[group][1]}'])
        servers[group][1].add_handler(midiHandler('send', None))
        servers[group][1]._init_protocols()

        print(f'Setting up {midiPorts[group][0]}')
        servers[group][0] = pymidi.server.Server.from_bind_addrs([f'0.0.0.0:{midiPorts[group][0]}'])
        servers[group][0].add_handler(midiHandler('receive', servers[group][1]))
        servers[group][0]._init_protocols()

    logger.info('Entering main loop')
    loopCounter = 0
    while True:
        for group in servers:
            try:
                servers[group][0]._loop_once(timeout=0)
                servers[group][1]._loop_once(timeout=0)
            except Exception as e:
                logger.error(f'Main loop failed: {e}')

        loopCounter += 1
        if loopCounter%50: continue

        try:
           messageList = sqs.receive_message(QueueUrl=queueUrl, WaitTimeSeconds=0, MaxNumberOfMessages=1).get('Messages', [])
        except Exception as e:
            logger.error(f'SQS receive failed: {e}')
            continue

        for message in messageList:
            body = json.loads(message['Body'])

            resetRange = body['range']
            port = int(body['port'])

            logger.info(f'Sending NoteOff to {port} for {portRanges[resetRange]}')

            for midiNote in portRanges[resetRange]:
                for channel in range(0, 16):
                    # Figure out the right socket to use here
                    sendNoteOff(servers[group][1], midiNote, channel)

            try:
                sqs.delete_message(QueueUrl=queueUrl, ReceiptHandle=message['ReceiptHandle'])
            except Exception as e:
                logger.error(f'SQS delete failed: {e}')

def alreadyRunning():
    global logger

    myName = os.path.basename(sys.argv[0])

    logger.debug('Checking to see if we are already running')
    output = os.popen('/usr/bin/ps -e').read()
    if output.count(myName) > 1: return True

    return False

def configure():
    global logger, location, midiPorts, connectInAndOut

    try:
        with open('midiports') as portsFile:
            portsList = portsFile.read()

        midiPorts = json.loads(portsList)
    except FileNotFoundError: # No ports file found - that's quite ok
        logger.info('No ports file found - using defaults')

        #
        # But because our stuck note fixer-upper needs to know the same port
        # numbers we will write out the values we're given.
        #
        with open('midiports', 'w') as portsFile:
            portsFile.write(json.dumps(midiPorts))
    except Exception as e:
        logger.warning(f'Got error {e} - ports file badly formatted?')

    logger.info(f'MIDI ports: {midiPorts}')

def interrupted(signal, frame):
    global logger

    logger.info('Interrupt - stopping')
    sys.exit(0)

if __name__ == '__main__':
    main()
