import boto3
import os
import logging

ec2 = boto3.client('ec2')

instanceId = os.environ.get('InstanceId')
rebootPassword = os.environ.get('RebootPassword')

logging.basicConfig()
logger = logging.getLogger()
logger.setLevel(logging.INFO)

def lambda_handler(event, context):
    global logger, instanceId
    
    if not instanceId or not rebootPassword:
        logger.error('Variables not set - stopping')
        return {'statusCode':500, 'body':'InstanceId not set'}
        
    password = event.get('rawQueryString')
    if not password:
        logger.error('TableName not set - stopping')
        return {'statusCode':401, 'body':'Say please'}
        
    if password != rebootPassword:
        logger.error('TableName not set - stopping')
        return {'statusCode':401, 'body':'Not for you'}
        
    try:
        ec2.reboot_instances(InstanceIds=[instanceId])
    except Exception as e:
        logger.error(f'Failed to reboot {instanceId}: {e}')
        return {'statusCode':200, 'body':'Failed'}
        
    return {'statusCode':200, 'body':'Ok'}
