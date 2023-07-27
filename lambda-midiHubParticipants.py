import json
import boto3
import os
import logging

dynamodb = boto3.client('dynamodb')

tableName = os.environ.get('TableName')

logging.basicConfig()
logger = logging.getLogger()
logger.setLevel(logging.INFO)

def lambda_handler(event, context):
    global logger, tableName
    
    if not tableName:
        logger.error('TableName not set - stopping')
        return {'statusCode':500, 'body':'TableName not set'}

    try:
        response = dynamodb.get_item(TableName=tableName, Key={'clientId':{'S':'Participants'}})
    except Exception as e:
        logger.error(f'Did not get participants: {e}')
        return {'statusCode':500, 'body':'Participants not found'}

    try:
        participants = json.loads(response['Item']['list']['S'])    
    except Exception as e:
        logger.error(f'Cloud not load participants: {e}')
        return {'statusCode':500, 'body':'Participants JSON error'}

    return(participants)
