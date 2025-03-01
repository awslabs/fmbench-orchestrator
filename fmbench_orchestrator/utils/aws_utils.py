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