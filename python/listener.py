#!/usr/bin/python3

from builtins import bytes

import logging
import select
import socket
import sys
import os
import signal
import json
import boto3
import alsa_midi
import threading

import pymidi.server
from pymidi.protocol import DataProtocol
from pymidi.protocol import ControlProtocol
from pymidi import packets
from pymidi.utils import get_timestamp

logger = None
outputSocket = None
remoteAddr = None
sequenceNumber = 0

class midiHandler(pymidi.server.Handler):
    def __init__(self, alsa):
        self.logger = logging.getLogger()
        self.alsaClient = alsa

    def on_peer_connected(self, peer):
        global remoteAddr

        self.logger.info(f'Peer connected: {peer}')
        remoteAddr = peer.addr

    def on_peer_disconnected(self, peer):
        self.logger.info(f'Peer disconnected: {peer}')

    def on_midi_commands(self, peer, midi_packet):
        for command in midi_packet.command.midi_list:
            event = None
            if command.command == 'note_on':
                event = alsa_midi.NoteOnEvent(note=command.params.key, velocity=command.params.velocity, channel=command.channel)
            elif command.command == 'note_off':
                event = alsa_midi.NoteOffEvent(note=command.params.key, velocity=command.params.velocity, channel=command.channel)
            elif command.command == 'aftertouch':
                event = alsa_midi.KeyPressureEvent(note=command.params.key, velocity=command.params.touch, channel=command.channel)
            elif command.command == 'pitch_bend_change':
                event = alsa_midi.PitchBendEvent(value=command.params.msb*256+command.params.lsb, channel=command.channel)
            elif command.command == 'control_mode_change':
                event = alsa_midi.ControlChangeEvent(param=command.params.controller, value=command.params.value, channel=command.channel)
            else:
                self.logger.warning(f'Unknown command: {command.command}')
                self.logger.warning(command)

            if event:
                self.logger.info(event)
                self.alsaClient.event_output(event)

        self.alsaClient.drain_output()

class myThread(threading.Thread):
    def __init__(self, alsaClient):
        threading.Thread.__init__(self)
        self.alsaClient = alsaClient

    def run(self):
        getAlsaInput(self.alsaClient)

def sendRtpCommand(event):
    global logger, sequenceNumber

    if not remoteAddr:
        logger.info('No-one is connected - not sending')
        return 

    header = {'rtp_header': {'flags': { 'v': 0x2,
                                        'p': 0,
                                        'x': 0,
                                        'cc': 0,
                                        'm': 0x1,
                                        'pt': 0x61,},
                             'sequence_number': sequenceNumber},
             'timestamp': get_timestamp(),
             'ssrc': outputSocket.ssrc}

    command = {'flags': {'b': 0,
                         'j': 0,
                         'z': 0,
                         'p': 0,
                         'len': 3},
               'midi_list': [event]}

    try:
        packet = packets.MIDIPacket.create(header=header, command=command, journal='')
    except Exception as e:
        logger.error(f'Failed to create packet: {e}')
        return

    try:
        outputSocket.sendto(packet, (remoteAddr[0], remoteAddr[1]+1))
        sequenceNumber += 1
    except Exception as e:
        logger.error(f'sendto failed: {e}')

def getAlsaInput(client):
    global logger

    while True:
        event = client.event_input()

        midi = {}
        midi['delta_time'] = 0
        midi['__next'] = 0x80
        try:
            midi['channel'] = event.channel
        except:
            pass # Ignore this if the event doens't have a channel number

        if event.type == alsa_midi.EventType.NOTEON:
            print(f'NoteOn note {event.note} velocity {event.velocity} channel {event.channel}')
            midi['command'] = 'note_on'
            midi['command_byte'] = packets.COMMAND_NOTE_ON | (event.channel &0xf)
            midi['params'] = {'key':event.note, 'velocity':event.velocity}
            sendRtpCommand(midi)
        elif event.type == alsa_midi.EventType.NOTEOFF:
            print(f'NoteOff note {event.note} velocity {event.velocity} channel {event.channel}')
            midi['command'] = 'note_off'
            midi['command_byte'] = packets.COMMAND_NOTE_OFF | (event.channel &0xf)
            midi['params'] = {'key':event.note, 'velocity':event.velocity}
            sendRtpCommand(midi)
        elif event.type == alsa_midi.EventType.CHANPRESS:
            print(f'KeyPressure note {event.note} velocity {event.velocity} channel {event.channel}')
            midi['command'] = 'aftertouch'
            midi['command_byte'] = packets.COMMAND_AFTERTOUCH | (event.channel &0xf)
            midi['params'] = {'key':event.note, 'velocity':event.velocity}
            sendRtpCommand(midi)
        elif event.type == alsa_midi.EventType.PITCHBEND:
            print(f'PitchBend value {event.value} channel {event.channel}')
            midi['command'] = 'pitch_bend_change'
            midi['command_byte'] = packets.COMMAND_PITCH_BEND_CHANGE | (event.channel &0xf)
            midi['params'] = {'lsb':event.value%256, 'msb':int(event.value/256)}
            sendRtpCommand(midi)
        elif event.type == alsa_midi.EventType.CONTROLLER:
            print(f'Controller param {event.param} value {event.value} channel {event.channel}')
            midi['command'] = 'control_mode_change'
            midi['command_byte'] = packets.COMMAND_CONTROL_MODE_CHANGE | (event.channel &0xf)
            midi['params'] = {'controller':event.param, 'value':event.value}
            sendRtpCommand(midi)
        elif event.type == alsa_midi.EventType.PORT_SUBSCRIBED:
            print(f'Connect: {event}')
        elif event.type == alsa_midi.EventType.PORT_UNSUBSCRIBED:
            print(f'Disconnect: {event}')
        elif event.type == alsa_midi.EventType.CONTROLLER:
            print(f'Controller: {event}')
        else:
            logger.warning(f'Unknown event: {event.type}')
            logger.warning(event)

def main():
    global logger, outputSocket

    signal.signal(signal.SIGINT, interrupted)

    logging.basicConfig()
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    if len(sys.argv) != 2:
        print(f'Usage: {sys.argv[0]} <UDP port>')
        sys.exit(0)

    myPort = int(sys.argv[1])

    alsaClient = alsa_midi.SequencerClient(f'rawhub-{myPort}')
    port = alsaClient.create_port(f'rawhub-{myPort}')

    alsaThread = myThread(alsaClient)
    alsaThread.start()

    rtpServer = pymidi.server.Server.from_bind_addrs([f'0.0.0.0:{myPort}'])
    rtpServer.add_handler(midiHandler(alsaClient))
    rtpServer._init_protocols()

    for socket in rtpServer.socket_map:
        if type(rtpServer.socket_map[socket]) is pymidi.protocol.DataProtocol:
            outputSocket = rtpServer.socket_map[socket]

    while True:
        rtpServer._loop_once(timeout=0)

def interrupted(signal, frame):
    global logger

    logger.info('Interrupt - stopping')
    sys.exit(0)

if __name__ == '__main__':
    main()
