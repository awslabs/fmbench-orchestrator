import boto3
import logging
from typing import Dict, Any, Optional
from fmbench_orchestrator.utils.logger import logger
from fmbench_orchestrator.utils.constants import *
from fmbench_orchestrator.utils.main_utils import get_latest_version


def create_ec2_instance(
    idx: int,
    key_name: str,
    security_group_id: str,
    user_data_script: str,
    ami: str,
    instance_type: str,
    iam_arn: str,
    region: str,
    device_name=DEFAULT_DEVICE_NAME,
    ebs_del_on_termination=True,
    ebs_Iops=EBS_IOPS,
    ebs_VolumeSize=EBS_VOLUME_SIZE,
    ebs_VolumeType=EBS_VOLUME_TYPE,
    CapacityReservationPreference=None,
    CapacityReservationId=None,
    CapacityReservationResourceGroupArn=None,
):
    """
    Create an EC2 instance with a startup script (user data) in the specified region.

    Args:
        idx (int): Index or identifier for the instance.
        key_name (str): The name of the key pair to associate with the instance.
        security_group_id (str): The ID of the security group to associate with the instance.
        user_data_script (str): The script to run on startup.
        ami (str): The ID of the AMI to use for the instance.
        instance_type (str): The type of instance to launch.
        iam_arn (str): The ARN of the IAM role to associate with the instance.
        region (str): The AWS region to launch the instance in.
        device_name (str): The device name for the EBS volume.
        ebs_del_on_termination (bool): Whether to delete the EBS volume on instance termination.
        ebs_Iops (int): The number of I/O operations per second for the EBS volume.
        ebs_VolumeSize (int): The size of the EBS volume in GiB.
        ebs_VolumeType (str): The type of EBS volume.
        CapacityReservationPreference (str): The capacity reservation preference.
        CapacityReservationTarget (dict): The capacity reservation target specifications.

    Returns:
        str: The ID of the created instance.
    """
    ec2_resource = boto3.resource("ec2", region_name=region)
    instance_id: Optional[str] = None
    try:
        instance_name: str = f"FMBench-{instance_type}-{idx}"
        
        # Prepare the CapacityReservationSpecification
        capacity_reservation_spec = {}
        if CapacityReservationId:
            capacity_reservation_spec["CapacityReservationTarget"] = {"CapacityReservationId": CapacityReservationId}
        elif CapacityReservationResourceGroupArn:
            capacity_reservation_spec["CapacityReservationTarget"] = {"CapacityReservationResourceGroupArn": CapacityReservationResourceGroupArn}
        elif CapacityReservationPreference:
            capacity_reservation_spec["CapacityReservationPreference"] = CapacityReservationPreference

        # Create a new EC2 instance with user data
        instances = ec2_resource.create_instances(
            BlockDeviceMappings=[
                {
                    "DeviceName": device_name,
                    "Ebs": {
                        "DeleteOnTermination": ebs_del_on_termination,
                        "Iops": ebs_Iops,
                        "VolumeSize": ebs_VolumeSize,
                        "VolumeType": ebs_VolumeType,
                    },
                },
            ],
            ImageId=ami,
            InstanceType=instance_type,  # Instance type
            KeyName=key_name,  # Name of the key pair
            SecurityGroupIds=[security_group_id],  # Security group ID
            UserData=user_data_script,  # The user data script to run on startup
            MinCount=MIN_INSTANCE_COUNT,  # Minimum number of instances to launch
            MaxCount=MAX_INSTANCE_COUNT,  # Maximum number of instances to launch
            IamInstanceProfile={  # IAM role to associate with the instance
                "Arn": iam_arn
            },
            CapacityReservationSpecification=capacity_reservation_spec,
            TagSpecifications=[
                {
                    "ResourceType": "instance",
                    "Tags": [{"Key": "Name", "Value": instance_name},
                             {"Key": "fmbench-version", "Value": get_latest_version()}],
                }
            ],
        )

        if instances:
            instance_id = instances[0].id
            logger.info(f"EC2 Instance '{instance_id}', '{instance_name}' created successfully with user data.")
        else:
            logger.error("Instances could not be created")
    except Exception as e:
        logger.error(f"Error creating EC2 instance: {e}")
        instance_id=None
    return instance_id


def delete_ec2_instance(instance_id: str, region: str) -> bool:
    """
    Deletes an EC2 instance given its instance ID.

    Args:
        instance_id (str): The ID of the instance to delete.
        region (str): The AWS region where the instance is located.

    Returns:
        bool: True if the instance was deleted successfully, False otherwise.
    """
    try:
        ec2_client = boto3.client("ec2", region_name=region)
        has_instance_terminated: Optional[bool] = None
        # Terminate the EC2 instance
        response = ec2_client.terminate_instances(InstanceIds=[instance_id])
        if response is not None:
            logger.info(f"Instance {instance_id} has been terminated.")
            has_instance_terminated = True
        else:
            logger.error(f"Instance {instance_id}  could not be terminated")
            has_instance_terminated = False
    except Exception as e:
        logger.info(f"Error deleting instance {instance_id}: {e}")
        has_instance_terminated = False
    return has_instance_terminated


