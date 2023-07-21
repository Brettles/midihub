#!/usr/bin/python3

#
# updatelatency.py
#  Intended to be run as a pipe destination. For example:
#   grep Latency *.log | updatelatency.py
#
#  Only processes lines from rtpmidid that have 'Latency' on them; takes the
#  client name, connected port and latency numbers and puts them into DynamoDB.
#  Expects there to be a local file called "dynamodbtable" with the name of the
#  table in it.
#  Output to DynamoDB is the maximum, minimum and last latency for each client
#  as well as the current timestamp.
#

import sys
import logging
import boto3
import time
import sys

logger = None
dynamodb = boto3.resource('dynamodb')

def main():
    global logger

    logging.basicConfig()
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    try:
        with open('dynamodbtable') as ddbfile:
            tableName = ddbfile.read().strip()
    except FileNotFoundError:
        logger.error('No table name file found - stopping')
        sys.exit(1)
    except Exception as e:
        logger.error(f'Cannot read table name: {e}')
        sys.exit(1)

    ddbTable = dynamodb.Table(tableName)
    latencyStats = {}

    for line in sys.stdin:
        latencyMarker = line.find('Latency')
        outputMarker = line.find('output')
        msMarker = line.find(' ms')

        if latencyMarker == -1 or outputMarker == -1 or msMarker == -1:
            logger.warning('No latency info found in input - ignoring')
            continue

        msNumber = line.index(':', latencyMarker)+2
        logMarker = line.index('.log')

        try:
            clientName = line[latencyMarker+8:msNumber-2]
            latencyValue = float(line[msNumber:msMarker-1])
            portNumber = int(line[outputMarker+7:logMarker])
        except Exception as e:
            logger.error(f'Failed to parse line: {e}')
            logger.error(line)
            continue

        id = f'{clientName}-{portNumber}'
        if id not in latencyStats: latencyStats[id] = []
        latencyStats[id].append(latencyValue)

    with ddbTable.batch_writer() as batch:
        for id in latencyStats:
            average = round(sum(latencyStats[id])/len(latencyStats[id]), 1)

            # Need to store floats as strings because DynamoDB doesn't support
            # float typess here
            item = {'clientId':id, 'timestamp':str(int(time.time())),
                    'lastLatency':str(latencyStats[id][-1]), 'averageLatency':str(average),
                    'maxLatency': str(max(latencyStats[id])), 'minLatency':str(min(latencyStats[id]))}
            batch.put_item(Item=item)

if __name__ == "__main__":
    main()
