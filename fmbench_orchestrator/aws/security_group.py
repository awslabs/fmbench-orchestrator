
import boto3
from typing import Optional
from botocore.exceptions import ClientError
from fmbench_orchestrator.utils.logger import logger
from fmbench_orchestrator.utils.aws import get_region
from fmbench_orchestrator.orchestrator.run import SecurityGroupConfig


def _get_security_group_id_by_name(region: str, group_name: str, vpc_id: int) -> str:
    """
    Retrieve the security group ID based on its name and VPC ID.

    Args:
        sg_name (str): The name of the security group.
        vpc_id (str): The ID of the VPC where the security group is located.
        region (str): The AWS region.

    Returns:
        str: The security group ID if found, None otherwise.
    """
    try:
        ec2_client = boto3.client("ec2", region_name=region)
        security_group_id: Optional[str] = None
        response = ec2_client.describe_security_groups(
            Filters=[
                {"Name": "group-name", "Values": [group_name]},
            ]
        )
        # If security group exists , return the ID
        if response["SecurityGroups"]:
            security_group_id = response["SecurityGroups"][0]["GroupId"]
        else:
            logger.error(f"Security group '{group_name}' not found in VPC '{vpc_id}'.")
    except Exception as e:
        logger.INFO(f"Error retrieving security group: {e}")
        security_group_id = None
    return security_group_id



def create_security_group(
    region: str, group_name: str, description: str, vpc_id: Optional[str] = None
):
    """
    Create an EC2 security group.

    Args:
        group_name (str): Name of the security group.
        description (str): Description of the security group.
        vpc_id (str, optional): ID of the VPC in which to create the security group. If None, it will be created in the default VPC.
        region (str): AWS region where the security group will be created.

    Returns:
        str: ID of the created security group.
    """
    try:
        # Initialize the EC2 client
        ec2_client = boto3.client("ec2", region_name=region)
        security_group_id: Optional[str] = None
        # Define parameters for creating the security group
        params: Dict = {
            "GroupName": group_name,
            "Description": description,
        }
        # Only add the VpcId parameter if vpc_id is not None
        if vpc_id is not None:
            params["VpcId"] = vpc_id

        # Create the security group
        response = ec2_client.create_security_group(**params)
        if response is not None:
            security_group_id = response["GroupId"]
            logger.info(f"Security Group Created: {security_group_id}")
        else:
            logger.error(f"Security group is not created.")
    except ClientError as e:
        # Check if the error is due to the group already existing
        if e.response["Error"]["Code"] == "InvalidGroup.Duplicate":
            print(
                f"Security Group '{group_name}' already exists. Fetching existing security group ID."
            )
            return _get_security_group_id_by_name(region, group_name, vpc_id)
        else:
            print(f"Error creating security group: {e}")
            security_group_id = None
    return security_group_id


def authorize_inbound_rules(security_group_id: str, region: str):
    """
    Authorize inbound rules to a security group.

    Args:
        security_group_id (str): ID of the security group.
        region (str): AWS region where the security group is located.
    """
    try:
        # Initialize the EC2 client
        ec2_client = boto3.client("ec2", region_name=region)
        # Authorize inbound rules
        ec2_client.authorize_security_group_ingress(
            GroupId=security_group_id,
            IpPermissions=[
                {
                    "IpProtocol": "tcp",
                    "FromPort": 22,
                    "ToPort": 22,
                    "IpRanges": [{"CidrIp": "0.0.0.0/0"}],  # Allow SSH from anywhere
                },
                {
                    "IpProtocol": "tcp",
                    "FromPort": 80,
                    "ToPort": 80,
                    "IpRanges": [{"CidrIp": "0.0.0.0/0"}],  # Allow HTTP from anywhere
                },
            ],
        )
        logger.info(f"Inbound rules added to Security Group {security_group_id}")
    except ClientError as e:
        if e.response["Error"]["Code"] == "InvalidPermission.Duplicate":
            logger.info(
                f"Inbound rule already exists for Security Group {security_group_id}. Skipping..."
            )
        else:
            logger.error(f"Error authorizing inbound rules: {e}")


def get_sg_id(region: str) -> str:
    # Append the region to the group name
    GROUP_NAME = f"{config_data['security_group'].get('group_name')}-{region}"
    DESCRIPTION = config_data["security_group"].get("description", " ")
    VPC_ID = config_data["security_group"].get("vpc_id")

    try:
        # Create or get the security group with the region-specific name
        sg_id = create_security_group(region, GROUP_NAME, DESCRIPTION, VPC_ID)
        logger.info(f"Security group '{GROUP_NAME}' created or imported in {region}")

        if sg_id:
            # Add inbound rules if security group was created or imported successfully
            authorize_inbound_rules(sg_id, region)
            logger.info(f"Inbound rules added to security group '{GROUP_NAME}'")

        return sg_id

    except ClientError as e:
        logger.error(
            f"An error occurred while creating or getting the security group '{GROUP_NAME}': {e}"
        )
        raise  # Re-raise the exception for further handling if needed
