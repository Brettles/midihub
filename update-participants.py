#!/usr/bin/python3

#
# update-participants.py
#  Get a list of MIDI participants and drop that into the DynamoDB table
#

import sys
import logging
import boto3
import sys
import os
import json

logger = None
dynamodb = boto3.resource('dynamodb')

def main():
    global logger

    logging.basicConfig()
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    try:
        with open('../dynamodbtable') as ddbfile:
            tableName = ddbfile.read().strip()
    except FileNotFoundError:
        logger.error('No table name file found - stopping')
        sys.exit(1)
    except Exception as e:
        logger.error(f'Cannot read table name: {e}')
        sys.exit(1)

    ddbTable = dynamodb.Table(tableName)
    participants = []

    output = os.popen('/usr/bin/aconnect -l').read().strip().split('\n')
    for line in output:
        if line.find('client') == 0: continue
        if line.find('    0 ') == 0: continue
        if line.find('Announce') > 0: continue
        if line.find('midiHub-') > 0: continue
        clientName = line[7:line.rindex("'")-1]
        participants.append(clientName)

    ddbTable.put_item(Item={'clientId':'Participants', 'list':json.dumps(participants)})

if __name__ == "__main__":
    main()
