# This script deploys the control node cloudformation, which will then automatically deploy and configure the cluster
# cloudformation and kubernetes deployment.

import os
import boto3
import re
import argparse
import json
from shutil import copyfile
import yaml

# This should never have to change. This is used in tagging/identifying all aws resources
project = "umsi-easy-hub"

# Loads from config.yaml. Currently, nothing from this file is actually needed at this point.
def load_config(tag="dev"):
    config = {}
    with open("config.yaml", 'r') as f:
        config = yaml.safe_load(f)
        config = {**config['common']}
        print(config)
        for c in config:
            if config[c] is None or config[c] == "":
                raise Exception("Error. {} does not have a valid value")
    
    return config

# Generate a new ssh key that will be used for all nodes throughout the deployment
def generate_ssh_key(config):
    ec2 = boto3.client('ec2')
    response = ec2.create_key_pair(KeyName='{}-{}'.format(config['project'], config['tag']))
    print(response)
    print(response['KeyMaterial'])

    with open("{}.pem".format(response['KeyName']), 'w') as f:
        f.write(response['KeyMaterial'])

    return response['KeyName']

# Create the S3 bucket that will centrally store scripts used throughout the deployment process
def create_bucket(config):
    print(config['account_id'])

    bucket_name = "{}-{}-{}".format(config['account_id'], config['project'], config['tag'])

    s3_client = boto3.client('s3')

    response = s3_client.create_bucket(ACL='private', Bucket=bucket_name)

    return bucket_name

# Helper script to generate S3 bucket name
def get_bucket_name(config):
    return "{}-{}-{}".format(config['account_id'], config['project'], config['tag'])

# Upload all scripts in the src/ folder to the S3 bucket
def upload_cluster_scripts(config):

    s3_resource = boto3.resource('s3')

    for filename in os.listdir('src'):
        print(filename)

        s3_resource.meta.client.upload_file('src/' + filename, get_bucket_name(config), filename)

    # Copy the ssh key to the s3 bucket so that the control node can eventually have it on it's hard drive.
    # You may need to ssh into the cluster nodes at some point in the future for debugging
    ssh_key = "{}.pem".format(config['ssh_key_name'])
    s3_resource.meta.client.upload_file(ssh_key, get_bucket_name(config), ssh_key)

# Deploy the control node cloudformation
def create_control_node(config):

    cf = boto3.client('cloudformation')

    with open('src/control_node_cf.yaml') as template_fileobj:
        template_data = template_fileobj.read()
    cf.validate_template(TemplateBody=template_data)

    response = cf.create_stack(
        StackName='{}-{}-control-node'.format(config['project'], config['tag']),
        TemplateBody=template_data,
        Parameters=[
            {
                'ParameterKey': 'BillingTag', 'ParameterValue': '{}-{}'.format(config['project'], config['tag']), 'UsePreviousValue': False
            },
            {
                'ParameterKey': 'ScriptBucket', 'ParameterValue': get_bucket_name(config), 'UsePreviousValue': False
            },
            {
                'ParameterKey': 'KeyName', 'ParameterValue': config['ssh_key_name'], 'UsePreviousValue': False
            },
            {
                'ParameterKey': 'Tag', 'ParameterValue': config['tag'], 'UsePreviousValue': False
            }
        ],
        Capabilities=[
            'CAPABILITY_NAMED_IAM'
        ],
    )
    print("deployed stack!")

if __name__ == "__main__":

    # The only argument required is the tag that makes this deployment and all its resources unique.
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", "-t", required=False, help="tag to build, must be alphanumeric like \"prod\" or \"test\"")

    args = parser.parse_args()

    # Default tag is "test"
    if args.tag is None:
        tag = "test"
    else:
        tag = args.tag

    # Generate basic config
    config = {}
    config['tag'] = tag
    config['project'] = project
    config['account_id'] = boto3.client('sts').get_caller_identity().get('Account')
    config['ssh_key_name'] = generate_ssh_key(config)
    print(config)

    # Create an S3 bucket
    create_bucket(config)

    # Upload all files in src/ to the bucket
    upload_cluster_scripts(config)

    # Finally, deploy the control node cloudformation
    create_control_node(config)