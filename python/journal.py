#!/usr/bin/python3

from pymidi import server
from pymidi import packets
from pymidi.utils import get_timestamp
import pymidi
import logging
import copy
import time
import sys

logging.basicConfig()
logger = logging.getLogger()
logger.setLevel(logging.INFO)

peerStatus = {}

class peerInfo():
    def __init__(self, peerId):
        self.logger = logging.getLogger()
        self.peerId = peerId
        self.sequenceNumber = None

        #
        # With guidance from RFC4696
        #
        self._status = {}
        self._status['pitchWheel'] = 0x2000

        self._status['noteOnTime'] = [None]*128
        self._status['noteOnSequenceNumber'] = [None]*128
        self._status['noteOnVelocity'] = [None]*128

        self._status['controllerValue'] = [None]*128
        self._status['controllerCount'] = [None]*128
        self._status['controllerToggle'] = [None]*128

        self._status['commandProgramNumber'] = None
        self._status['commabdBankMsb'] = None
        self._status['commabdBankLsb'] = None

        self.channelInfo = [self._status]*16

    def __str__(self):
        return f'peerId {self.peerId} sequenceNumber {self.sequenceNumber}'

    def pitchWheel(self, channel, value=0x2000):
        self.channelInfo[channel]['pitchWheel'] = value
    
    def noteOn(self, channel, note, velocity=0):
        noteNumber = int(note)
        self.channelInfo[channel]['noteOnTime'][noteNumber] = time.time()
        self.channelInfo[channel]['noteOnSequenceNumber'][noteNumber] = self.sequenceNumber
        self.channelInfo[channel]['noteOnVelocity'][noteNumber] = velocity

    def noteOff(self, channel, note):
        self.noteOn(channel, note, 0) # A velocity of zero indicates NoteOff

    def controlMode(self, channel, controller, value):
        self.channelInfo[channel]['controllerValue'][controller] = value

class MyHandler(server.Handler):
    def on_peer_connected(self, peer):
        print(f'Peer connected: {peer}')
        peerStatus[peer.name] = peerInfo(peer.name)

    def on_peer_disconnected(self, peer):
        print(f'Peer disconnected: {peer}')
        peerStatus.pop(peer.name, None)

    def on_midi_commands(self, peer, midi_packet):
        if processJournal(peer, midi_packet):
            for command in midi_packet.command.midi_list:
                print(f'{peer.name} sent {command.command}')
                if command.command == 'note_on':
                    peerStatus[peer.name].noteOn(command.channel, command.params.key, command.params.velocity)
                    print('Note on: '+hex(int(command.params.key)))
                elif command.command == 'note_off':
                    peerStatus[peer.name].noteOff(command.channel, command.params.key)
                    print('Note off: '+hex(int(command.params.key)))
                elif command.command == 'aftertouch':
                    pass
                elif command.command == 'pitch_bend_change':
                    peerStatus[peer.name].pitchWheel(command.channel, command.params.msb*256+command.params.lsb)
                elif command.command == 'control_mode_change':
                    peerStatus[peer.name].controlMode(command.channel, command.params.controller, command.params.value)

def processJournal(peer, packet):
    journal = packet.journal
    sequenceNumber = packet.header.rtp_header.sequence_number

    if not peerStatus[peer.name].sequenceNumber: # This is the first packet from this peer
        peerStatus[peer.name].sequenceNumber = sequenceNumber
        return True

    if not journal: return True

    if sequenceNumber < peerStatus[peer.name].sequenceNumber: # Out of order packet
        logger.warning(f'This seq={sequenceNumber} < last={peerStatus[peer.name].sequenceNumber} - skipping')
        return False

    if sequenceNumber > peerStatus[peer.name].sequenceNumber+1: # We have missed a packet somewhere
        if not journal.header.a:
            logger.warning('Missed packets but no journal present - continuing')
        elif sequenceNumber == peerStatus[peer.name].sequenceNumber-1 and journal.header.s: # Single packet loss
            logger.warning('Single packet loss identified - continuing')
        else:
            logger.warning(f'This seq={sequenceNumber} > last={peerStatus[peer.name].sequenceNumber} - processing journal')

    if not journal.header.a and not journal.header.y: print('Empty journal')
    if journal.header.y: print('System journal is in the recovery journal')
    if journal.header.a: print(f'Channel journals present: {journal.header.totchan+1}')
    if journal.header.s: print('Single packet loss')
    if journal.header.h: print('Enhanced chapter C encoding')

    if journal.system_journal:
        print('--- System Journal ---')
        print(journal.system_journal)
        print('----------------------')

    if journal.header.a:
        channel = journal.channel_journal
        print('--- Channel Journal ---')
        print(f'Channel: {channel.header.chan} Length: {channel.header.length}')
        if channel.header.h: print('Enhanced chapter C encoding') # I have no idea what to do with this

        # Actual order of chapters is below:
        if channel.header.p: print('Program change')
        if channel.header.c: print('Control change')
        if channel.header.m: print('Parameter system')
        if channel.header.w: print('Pitch wheel')
        if channel.header.e: print('Note extras')
        if channel.header.t: print('Channel aftertouch')
        if channel.header.a: print('Poly aftertouch')

        index = 0 # All references below are to RFC6295

        if channel.header.p: # Fixed size of three octets - Appendix A.2
            index += 3

        if channel.header.c: # Appendix A.3
            headerFirst = channel.journal[index]
            length = headerFirst & 0x7f
            index += length
            print(f' - Control change is {length} bytes')

        if channel.header.m: # Appendix A.4
            headerFirst = channel.journal[index]&0x03
            headerSecond = channel.journal[index+1]
            length = headerFirst*256+headerSecond
            index += length
            print(f' - Parameter change is {length} bytes')

        if channel.header.w: # Fixed size of two octets - Appendix A.5
            wheelFirst = channel.journal[index]&0x7f
            wheelSecond = channel.journal[index+1]&0x7f
            pitchWheelValue = wheelFirst*256+wheelSecond
            index += 2

        if channel.header.n: # Appendix A.6
            print('Note on/off')

            headerFirst = channel.journal[index]
            if headerFirst&0x80: print('B (s-bit) set - previous packet had a NoteOff in it')
            length = headerFirst & 0x7f

            if length*2 > len(channel.journal)-2:
                print(f'WARNING: note on/off header says length is {length*2} but actual length is {len(channel.journal)-2}')
                return # Not the right thing to do - deal with this later

            headerSecond = channel.journal[index+1]
            high = headerSecond & 0x0f
            low = (headerSecond & 0xf0) >> 4

            print(f'header: {hex(headerFirst)} {hex(headerSecond)} bitfield length (duo-octets): {length} channel-header-len {channel.header.length} channel-journal-len {len(channel.journal)} low: {low} high: {high} journal-len {len(journal)}')
            index += 2
            for i in range(length): # Length is data length in two-octet bursts
                print(hex(channel.journal[index]), hex(channel.journal[index+1]))
                index += 2


        if channel.header.e: # Appendix A.7
            headerFirst = channel.journal[index]
            length = headerFirst & 0x7f
            index += length
            print(f' - Extras is {length} bytes')

        if channel.header.t: # Fixed size of one octet - Appendix A.8
            index += 1

        if channel.header.a: # Appendix A.9
            headerFirst = channel.journal[index]
            length = headerFirst & 0x7f
            index += length
            print(f' - Aftertouch is {length} bytes')

        print('-----------------------')

    peerStatus[peer.name].sequenceNumber = sequenceNumber
    return True

myServer = server.Server([('0.0.0.0', 5140)])
myServer.add_handler(MyHandler())
myServer._init_protocols()

while True:
    myServer._loop_once()
