import boto3
import requests
import os
from fmbench_orchestrator.utils.logger import logger    

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
