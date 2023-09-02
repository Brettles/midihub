#!/usr/bin/python3

from builtins import bytes

from optparse import OptionParser
import logging
import select
import socket
import sys
import time
import random

import pymidi.client
from pymidi.protocol import DataProtocol
from pymidi.protocol import ControlProtocol
from pymidi import utils
from pymidi import packets
from pymidi import protocol
from pymidi.utils import get_timestamp

host = '0.0.0.0'
port = 5004

try:
    import coloredlogs
except ImportError:
    coloredlogs = None

logger = logging.getLogger('pymidi.examples.server')

DEFAULT_BIND_ADDR = '0.0.0.0:5051'

parser = OptionParser()
parser.add_option(
    '-b',
    '--bind_addr',
    dest='bind_addrs',
    action='append',
    default=None,
    help='<ip>:<port> for listening; may give multiple times; default {}'.format(DEFAULT_BIND_ADDR),
)
parser.add_option(
    '-v', '--verbose', action='store_true', dest='verbose', default=False, help='show verbose logs'
)


def sendPacket(command, note, client):
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
            'timestamp': get_timestamp(),
            'ssrc': client.ssrc
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
                        'key': note,
                        'velocity': 80,
                    }
                }
            ]
        },
        journal=''
    )

    client.socket[1].sendto(packet, (host, port+1))

def sendMultiNotePacket(client):
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
            'timestamp': get_timestamp(),
            'ssrc': client.ssrc
        },
        command={
            'flags': {
                'b': 0,
                'j': 0,
                'z': 0,
                'p': 0,
                'len': 7,
            },
            'midi_list': [
                {
                    'delta_time': 0,
                    '__next': 0x80,
                    'command': 'note_on',
                    'command_byte': packets.COMMAND_NOTE_ON | (channel & 0xF),
                    'channel': channel,
                    'params': {
                        'key': 'B6',
                        'velocity': 80,
                    }
                },
                {
                    'delta_time': 2,
                    '__next': 0x80,
                    'command': 'note_on',
                    'command_byte': packets.COMMAND_NOTE_OFF | (channel & 0xF),
                    'channel': channel,
                    'params': {
                        'key': 'B6',
                        'velocity': 80,
                    }
                }
            ]
        },
        journal=''
    )

    client.socket[1].sendto(packet, (host, port+1))

def main():
    options, args = parser.parse_args()

    log_level = logging.DEBUG if options.verbose else logging.INFO
    if coloredlogs:
        coloredlogs.install(level=log_level)
    else:
        logging.basicConfig(level=log_level)

    client = pymidi.client.Client(sourcePort=5082, name='PyMidi-bl')
    logger.info(f'Connecting to RTP-MIDI server @ {host}:{port} ...')
    client.connect(host, port)
    logger.info('Connecting!')
#    while True:
    for i in range (1, 5):
        logger.info('Striking key...')
#        sendMultiNotePacket(client)
        sendPacket(packets.COMMAND_NOTE_ON, 'B6', client)
#        client.send_note_on('B6')
        time.sleep(0.5)
        sendPacket(packets.COMMAND_NOTE_OFF, 'B6', client)
#        client.send_note_off('B6')
        time.sleep(0.5)

    client.disconnect()

main()
