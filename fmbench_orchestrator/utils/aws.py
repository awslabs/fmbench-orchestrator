import os
import boto3
import requests
from typing import Tuple, Optional
from fmbench_orchestrator.utils.logger import logger
from fmbench_orchestrator.utils.constants import *
from fmbench_orchestrator.aws.key_pair import create_key_pair
from botocore.exceptions import ClientError, NoCredentialsError 
from fmbench_orchestrator.aws.security_group import authorize_inbound_rules, create_security_group



def get_region() -> str:
    """
    This function fetches the current region where this orchestrator is running using the 
    EC2 region metadata API or the boto3 session if the region cannot be determined from
    the API.
    """
    try:
        session = boto3.session.Session()
        region_name = session.region_name
        if region_name is None:
            logger.info(
                f"boto3.session.Session().region_name is {region_name}, "
                f"going to use an metadata api to determine region name"
            )
            # THIS CODE ASSUMED WE ARE RUNNING ON EC2, for everything else
            # the boto3 session should be sufficient to retrieve region name
            resp = requests.put(
                "http://169.254.169.254/latest/api/token",
                headers={"X-aws-ec2-metadata-token-ttl-seconds": "21600"},
            )
            token = resp.text
            region_name = requests.get(
                "http://169.254.169.254/latest/meta-data/placement/region",
                headers={"X-aws-ec2-metadata-token": token},
            ).text
            logger.info(
                f"region_name={region_name}, also setting the AWS_DEFAULT_REGION env var"
            )
            os.environ["AWS_DEFAULT_REGION"] = region_name
        logger.info(f"region_name={region_name}")
    except Exception as e:
        logger.error(f"Could not fetch the region: {e}")
        region_name = None
    return region_name

def _determine_username(ami_id: str, region: str):
    """
    Determine the appropriate username based on the AMI ID or name.

    Args:
        ami_id (str): The ID of the AMI used to launch the EC2 instance.

    Returns:
        str: The username for the EC2 instance.
    """
    try:
        ec2_client = boto3.client("ec2", region)
        # Describe the AMI to get its name
        response = ec2_client.describe_images(ImageIds=[ami_id])
        ec2_username: Optional[str] = None
        if response is not None:
            ami_name = response["Images"][0][
                "Name"
            ].lower()  # Convert AMI name to lowercase
        else:
            logger.error(f"Could not describe the ec2 image")
            return
        # Match the AMI name to determine the username
        for key in AMI_USERNAME_MAP:
            if key in ami_name:
                return AMI_USERNAME_MAP[key]

        # Default username if no match is found
        ec2_username = DEFAULT_EC2_USERNAME
    except Exception as e:
        logger.info(f"Error fetching AMI details: {e}")
        ec2_username = DEFAULT_EC2_USERNAME
    return ec2_username

def _get_ec2_hostname_and_username(
    instance_id: str, region: str, public_dns=True
) -> Tuple:
    """
    Retrieve the public or private DNS name (hostname) and username of an EC2 instance.
    Args:
        instance_id (str): The ID of the EC2 instance.
        region (str): The AWS region where the instance is located.
        public_dns (bool): If True, returns the public DNS; if False, returns the private DNS.

    Returns:
        tuple: A tuple containing the hostname (public or private DNS) and username.
    """
    try:
        hostname, username, instance_name = None, None, None
        ec2_client = boto3.client("ec2", region_name=region)
        # Describe the instance
        response = ec2_client.describe_instances(InstanceIds=[instance_id])
        if response is not None:
            # Extract instance information
            instance = response["Reservations"][0]["Instances"][0]
            ami_id = instance.get(
                "ImageId"
            )  # Get the AMI ID used to launch the instance
            # Check if the public DNS or private DNS is required
            if public_dns:
                hostname = instance.get("PublicDnsName")
            else:
                hostname = instance.get("PrivateDnsName")
            # instance name
            tags = response["Reservations"][0]["Instances"][0]["Tags"]
            logger.info(f"tags={tags}")
            instance_names = [t["Value"] for t in tags if t["Key"] == "Name"]
            if not instance_names:
                instance_name = "FMBench-" + instance.get('InstanceType') + "-" + instance_id
            else:
                instance_name = instance_names[0]
        # Determine the username based on the AMI ID
        username = _determine_username(ami_id, region)
    except Exception as e:
        logger.info(f"Error fetching instance details (hostname and username): {e}")
    return hostname, username, instance_name


def get_iam_role() -> str:
    try:
        caller = boto3.client("sts").get_caller_identity()
        account_id = caller.get("Account")
        role_arn_from_env = os.environ.get("FMBENCH_ROLE_ARN")
        if role_arn_from_env:
            print(f"role_arn_from_env={role_arn_from_env}, using it to set arn_string")
            arn_string = role_arn_from_env
        else:
            print(
                f"role_arn_from_env={role_arn_from_env}, using current sts caller identity to set arn_string"
            )
            arn_string = caller.get("Arn")

            # if this is an assumed role then remove the assumed role related pieces
            # because we are also using this role for deploying the SageMaker endpoint
            # arn:aws:sts::015469603702:assumed-role/SSMDefaultRoleForOneClickPvreReporting/i-0c5bba16a8b3dac51
            # should be converted to arn:aws:iam::015469603702:role/SSMDefaultRoleForOneClickPvreReporting
            if ":assumed-role/" in arn_string:
                role_name = arn_string.split("/")[-2]
                arn_string = f"arn:aws:iam::{account_id}:instance-profile/{role_name}"
                print(
                    f"the sts role is an assumed role, setting arn_string to {arn_string}"
                )
            else:
                arn_string = caller.get("Arn")
        role_name = arn_string.split("/")[-1]
    except Exception as e:
        logger.error(f"Could not fetch the role name or arn_string: {e}")
        arn_string = None

    return arn_string


def create_iam_instance_profile_arn():

    iam_client = boto3.client("iam")
    role_name: str = "fmbench"

    instance_profile_arn: Optional[str] = None
    instance_profile_role_name: str = config_data["aws"].get(
        "iam_instance_profile_arn", "fmbench_orchestrator_role_new"
    )

    try:
        policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": [
                        "ecr:GetAuthorizationToken",
                        "ecr:BatchCheckLayerAvailability",
                        "ecr:GetDownloadUrlForLayer",
                        "ecr:BatchGetImage",
                        "ecr:ListImages",
                    ],
                    "Resource": "*",
                },
                {
                    "Effect": "Allow",
                    "Action": [
                        "ec2:RunInstances",
                        "ec2:DescribeInstances",
                        "ec2:CreateTags",
                        "ec2:StartInstances",
                        "ec2:StopInstances",
                        "ec2:RebootInstances",
                    ],
                    "Resource": [
                        "arn:aws:ec2:*:*:instance/*",
                        "arn:aws:ec2:*:*:volume/*",
                        "arn:aws:ec2:*:*:network-interface/*",
                        "arn:aws:ec2:*:*:key-pair/*",
                        "arn:aws:ec2:*:*:security-group/*",
                        "arn:aws:ec2:*:*:subnet/*",
                        "arn:aws:ec2:*:*:image/*",
                    ],
                },
                {
                    "Effect": "Allow",
                    "Action": [
                        "ec2:CreateSecurityGroup",
                        "ec2:AuthorizeSecurityGroupIngress",
                        "ec2:AuthorizeSecurityGroupEgress",
                        "ec2:DescribeSecurityGroups",
                    ],
                    "Resource": "*",
                },
                {
                    "Effect": "Allow",
                    "Action": ["ec2:CreateKeyPair", "ec2:DescribeKeyPairs"],
                    "Resource": "*",
                },
                {
                    "Effect": "Allow",
                    "Action": [
                        "ec2:CreateTags",
                        "ec2:DescribeInstances",
                        "ec2:TerminateInstances",
                        "ec2:DescribeInstanceStatus",
                        "ec2:DescribeAddresses",
                        "ec2:AssociateAddress",
                        "ec2:DisassociateAddress",
                        "ec2:DescribeRegions",
                        "ec2:DescribeImages",
                        "ec2:DescribeAvailabilityZones",
                    ],
                    "Resource": "*",
                },
                {
                    "Effect": "Allow",
                    "Action": "iam:PassRole",
                    "Resource": [f"arn:aws:iam::*:role/{role_name}*"],
                },
            ],
        }

        policy_response = iam_client.create_policy(
            PolicyName="CustomPolicy", PolicyDocument=json.dumps(policy)
        )

        # Create IAM role
        assume_role_policy_document = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {"Service": "ec2.amazonaws.com"},
                    "Action": "sts:AssumeRole",
                }
            ],
        }

        iam_client.create_role(
            RoleName=instance_profile_role_name,
            AssumeRolePolicyDocument=json.dumps(assume_role_policy_document),
        )

        iam_client.attach_role_policy(
            RoleName=instance_profile_role_name,
            PolicyArn=policy_response["Policy"]["Arn"],
        )

        # Attach managed policies to the role
        managed_policies = [
            "arn:aws:iam::aws:policy/AmazonSageMakerFullAccess",
            "arn:aws:iam::aws:policy/AmazonS3FullAccess",
            "arn:aws:iam::aws:policy/AWSCloudFormationReadOnlyAccess",
            "arn:aws:iam::aws:policy/AmazonBedrockFullAccess",
        ]

        for policy_arn in managed_policies:
            iam_client.attach_role_policy(
                RoleName=instance_profile_role_name, PolicyArn=policy_arn
            )

        # Create instance profile
        instance_profile_info = iam_client.create_instance_profile(
            InstanceProfileName="FMBenchOrchestratorInstanceProfile_new"
        )

        if instance_profile_info is not None:
            logger.info(f"Instance profile created: {instance_profile_info}")
            instance_profile_arn = instance_profile_info["InstanceProfile"].get("Arn")

        # Add role to instance profile
        iam_client.add_role_to_instance_profile(
            InstanceProfileName="FMBenchOrchestratorInstanceProfile_new",
            RoleName=instance_profile_role_name,
        )

        print("Instance profile created and role attached successfully.")
        return instance_profile_arn
    except ClientError as e:
        if e.response["Error"]["Code"] == "InvalidPermission.Duplicate":
            logger.info(f"Iam instance profile already exists. Skipping...")
        else:
            logger.error(f"Error creating the instance profile iam: {e}")


def upload_and_run_script(
    instance_id: str,
    private_key_path: str,
    user_data_script: str,
    region: str,
    startup_script: str,
) -> bool:
    """
    Runs the user data as a script in the case of which an instance is pre existing. This is because
    the user script of an instance can only be modified when it is stopped.
    """
    ec2_client = boto3.client("ec2", region_name=region)
    has_start_up_script_executed: bool = False
    try:
        # Get instance public IP
        public_hostname, username, instance_name = _get_ec2_hostname_and_username(
            instance_id, region, public_dns=True
        )
        logger.info(f"Uploading and running script on instance {instance_id}...")
        logger.info(
            f"hostname={public_hostname}, username={username}, instance_name={instance_name}"
        )
        # Create SSH client
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        # Connect to the instance
        ssh.connect(
            hostname=public_hostname, username=username, key_filename=private_key_path
        )

        # Upload the script
        with ssh.open_sftp() as sftp:
            with sftp.file("/tmp/startup_script.sh", "w") as f:
                f.write(user_data_script)

        # Make the script executable and run it
        stdin, stdout, stderr = ssh.exec_command(
            "chmod +x /tmp/startup_script.sh && nohup sudo /tmp/startup_script.sh &"
        )

        # Print output
        # for line in stdout:
        #     logger.info(line.strip('\n'))
        # for line in stderr:
        #     logger.info(line.strip('\n'))
        ssh.close()
        logger.info(f"Script uploaded and executed on instance {instance_id}")
        has_start_up_script_executed = True
    except Exception as e:
        logger.error(
            f"Error uploading and running script on instance {instance_id}: {e}"
        )
    return has_start_up_script_executed


