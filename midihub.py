#!/usr/bin/python3

#
# midihub.py
#  Create and maintains a set of rtpMIDI daemon processes that act as a hub
#  for remote musicians. Tested and running on Ubuntu 20.04; unsure about
#  other distros.
#
#  On its own, the MIDI daemon allows connections to itself and registers
#  those client connections with Alsa (Linux sound library and utilities).
#  This is great if you're running a mixer in a GUI on the host but we're
#  not doing that - we want to enable MIDI collaboration between remote
#  participants on a "headless" server with no local MIDI resources on the
#  host.
#
#  To do this we can get Alsa to connect MIDI participants together as if
#  they were local MIDI devices. This utility automatically joins all
#  participants connected to a specific MIDI client (or port) together.
#  Essentially, this mimics a bunch of MIDI devices connected to each other
#  via cables in the same room but this is over the internet.
#
#  Prerequisite Ubuntu packages:
#   cmake g++ pkt-config libavahi-client-dev libfmt-dev alsa-utils alsa-base
#   libghc-alsa-core-dev avahi-utils linux-modules-extra-`uname -r`
#
#  Source for the RTP MIDI daemon:
#   https://github.com/davidmoreno/rtpmidid
#

import sys
import os
import logging
import signal
import time
import subprocess
import re
import boto3
import requests
import json

#
# Configuration:
#  SLEEP_CHECK_INTERVAL:
#      How often to check that the daemon(s) are running and when ned
#      participants have joined. Default is five seconds which seems
#      reasonable.
#  MIDI_DAEMON:
#      Path to the RTP MIDI daemon.
#
#  midiPorts:
#      List of ports to open to listen to MIDI connections. Each port will
#      be opened as a separate process using the RTP MIDI daemon.
#      These can also be configured by creating a file in the running
#      directory called "midiports". Put a comma-seperate list of ports into
#      the file and it will be read during startup or if SIGHUP is sent.
#
SLEEP_CHECK_INTERVAL = 5
MIDI_DAEMON = 'rtpmidid/build/src/rtpmidid'

midiPorts = [5004, 5006]
logger = None
location = ''

#
# Main loop which does a few startup checks and runs forever.
# Checks to make sure all of the daemons are running which is important at
# startup but also just in case they crash at some point.
# After that, looks at the participants on each daemon and automatically
# joins all of the MIDI sessions to each other - acting as a type of hub.
#
def main():
    global logger

    signal.signal(signal.SIGINT, interrupted)
    signal.signal(signal.SIGHUP, configure)

    configure('', '')

    if alreadyRunning():
        logger.info('This is the second copy - stopping')
        sys.exit(0)

    if not checkPrerequisites():
        sys.exit(1)

    logger.info('Entering main loop')
    while True:
        checkDaemon()
        checkMidiParticipants()

        time.sleep(SLEEP_CHECK_INTERVAL)

#
# See if we have daemons running on the ports specified in the global
# midiPorts list. If we don't find a process running with the name of
# the daemon and the port number then we fork() and create one.
#
def checkDaemon():
    global logger, midiPorts

    midiStatus = {}
    daemonName = os.path.basename(MIDI_DAEMON)

    stream = os.popen('/usr/bin/ps -ef')
    psLine = stream.readline()
    while psLine:
        if psLine.find(daemonName) > -1:
            for port in midiPorts:
                if psLine.find(str(port)) > -1:
                    midiStatus[port] = True
                    break
        psLine = stream.readline()

    for port in midiPorts:
        if port in midiStatus: continue
        logger.warning(f'Midi daemon on port {port} not running - starting')
        if os.fork() == 0: # We are the child process
            newStdOut = os.open(f'output-{port}.log', os.O_WRONLY|os.O_CREAT|os.O_APPEND)
            os.dup2(newStdOut, sys.stdout.fileno())
            os.close(newStdOut)
            os.close(2) # Close STDERR
            os.execlp(MIDI_DAEMON, daemonName, f'--port', str(port), '--control', f'control-{port}.sock', '--name', f'midiHub-{location}{port}')

#
# Using the aconnect command we can see all of the MIDI "ports" or "clients"
# that are open on this server; and all of the participants in those ports.
# We're not interested in the low numbered prots (below 128) - when the MIDI
# daemon starts it is allocated a port number from 128 upwards.
#
# Using the output we find all of the participants in the high numbered ports
# and then join them all together. They could already be joined together but
# aconnect doesn't care if we try to join two participants together that are
# already joined to each other. We want to create a mesh between the
# participants on each port/client; but not between ports/clients.
#
# Each port/client from the MIDI daemon will already have a "Network"
# participants with a participant number of zero. The daemon will also
# automatically discover the other daemons that are running so we ignore any
# other participants with "midiHub" in the name. We only want to connect
# remote participants to each other. We definitely don't want to connect
# the daemons to each other - that's a valid MIDI configuration but not
# suitable for our purposes here.
#
def checkMidiParticipants():
    logger.debug('Getting output from aconnect')
    output = os.popen('aconnect -l').read().split('\n')
    for index in range(0,len(output)):
        logger.debug(f'Line: {output[index]}')
        if output[index].find('client ') == 0:
            try:
                clientNumber = re.findall(r'\d+', output[index])[0]
            except:
                logger.warning(f'Did not see client id in {output[index]} - skipping')
                continue
            if int(clientNumber) < 128: continue

            participants = {}
            for search in range(index+1,len(output)):
                logger.debug(f'  Search: {output[index]}')
                if output[search].find('client') == 0: break
                if output[search].find('Network') > -1: continue
                if output[search].find('midiHub') > -1: continue
                if output[search].find('Connect') > -1: continue
                if not len(output[search]): continue

                try:
                    participantNumber = re.findall(r'\d+', output[search])[0]
                    participantName   = re.findall(r"'.+'", output[search])[0][1:-1].strip()
                    participants[participantNumber] = participantName
                except:
                    logger.warning(f'Did not see participant info in {output[search]} - skipping')
                    break

            if len(participants) > 1:
                logger.info(f'client {clientNumber}: {participants}')
                for sourceConnection in participants.keys():
                    for destConnection in participants.keys():
                        if sourceConnection == destConnection: continue
                        logger.debug(f'Adding connection in {clientNumber} for {sourceConnection} and {destConnection}')
                        os.system(f'aconnect {clientNumber}:{sourceConnection} {clientNumber}:{destConnection} >/dev/null 2>&1')

#
# Although it's not completely harmful we don't really want more than one
# copy of this running at any one time. The worst that can happen is that
# two copies of this script will try and run multiple copies of the daemon
# on the same ports - but the UDP port can only be bound to a single process
# so any subsequent daemon invocations will self-terminate. This script will
# also try and connect MIDI participants to each other but additional
# connection requests will be ignored if the connection already exists.
#
def alreadyRunning():
    global logger

    myName = os.path.basename(sys.argv[0])

    logger.debug('Checking to see if we are already running')
    output = os.popen('/usr/bin/ps -e').read()
    if output.count(myName) > 1: return True

    return False

#
# There's no point trying to run the MIDI daemon if there aren't a few
# drivers running on the system (soundcore and snd-dummy); and we want
# to make sure that the MIDI daemon itself is here somewhere too.
#
def checkPrerequisites():
    global logger

    logger.debug('Checking for soundcore module')
    output = os.popen('/usr/sbin/modinfo soundcore 2>&1').read()
    if output.find('not found') > -1:
        logger.warning('Kernel module soundcore not found - stopping')
        return False

    logger.debug('Checking for snd-dummy module')
    output = os.popen('/usr/sbin/modinfo snd-dummy 2>&1').read()
    if output.find('not found') > -1:
        logger.warning('Kernel module snd-dummy not found - stopping')
        return False

    logger.debug('Checking for MIDI daemon code')
    if not os.path.isfile(MIDI_DAEMON):
        logger.warning(f'Midi daemon not found at {MIDI_DAEMON} - stopping')
        return False

    return True

#
# A few things to do here.
# First we look for our configuration file which (if it exists) contains a
# comma-separated list of UDP ports that we are to listen to. If it's empty
# or malformed then we go with the defaults set at the start of this file.
# Next we try and set a "nice" display name for the ports that we're going to
# create. This is just window dressing but if there are a few of these running
# around the world it's nice to know which one you're connected to. We look
# for the AWS instance metadata - if it doesn't exist, no "nice" name. No big
# deal. If it exists then we get a list of regions from Lightsail - because it
# has a nice mapping of AWS region name to "human readable" name. But Lightsail
# isn't in every AWS region so this might fail - if it does, again, not "nice"
# name.
# This is also called if we're sent SIGHUP mainly so that we can re-read the
# ports configuration file.
#
def configure(singal, frame):
    global logger, location, midiPorts

    logging.basicConfig()
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    try:
        with open('midiports') as portsFile:
            portsList = portsFile.read()

        newPortsList = []
        for port in portsList.split(','):
            newPortsList.append(int(port))
        if len(newPortsList):
            midiPorts = newPortsList
    except FileNotFoundError: # No ports file found - that's quite ok
        logger.info('No ports file found - using defaults')
    except Exception as e:
        logger.warning(f'Got error {e} - ports file badly formatted?')

    logger.info(f'MIDI ports: {midiPorts}')

    try:
        response = requests.get('http://169.254.169.254/latest/dynamic/instance-identity/document')
        instanceInfo = json.loads(response.content)
    except:
        logger.info('Did not get instance metadata - will not set location')
        return

    regionName = instanceInfo.get('region')
    if not regionName:
        logger.warning('No region name in instance metadata - will not set location')
        return

    lightsail = boto3.client('lightsail')
    try:
        regionInfo = lightsail.get_regions().get('regions')
    except Exception as e:
        logger.info(f'Cannot get Lightsail region info - will not set location: {e}')
        return

    for region in regionInfo:
        if region['name'] == regionName:
            location = region['displayName']+'-'
            logger.info(f'Location set to {region["displayName"]}')
            break
    else:
        logger.info(f'Did not find printable name for {regionName}')

def interrupted(signal, frame):
    global logger

    logger.info('Interrupt - stopping')
    sys.exit(0)

if __name__ == "__main__":
    main()
