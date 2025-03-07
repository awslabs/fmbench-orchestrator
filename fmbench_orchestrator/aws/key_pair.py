import os
import boto3
from pathlib import Path
from typing import Optional, Tuple
from botocore.exceptions import ClientError
from fmbench_orchestrator.utils.logger import logger


def create_key_pair(key_name: str, region: str, delete_key_pair_if_present: bool) -> str:
    """
    Create a new key pair for EC2 instances.

    Args:
        key_name (str): The name of the key pair.
        region (str): AWS region where the key pair will be created.
        delete_key_pair_if_present (bool): Whether to delete existing key pair if it exists.

    Returns:
        str: The private key material in PEM format if successful, None if failed.

    Raises:
        ClientError: If there is an error interacting with AWS EC2 API.
    """
    try:
        # Initialize the EC2 client
        ec2_client = boto3.client("ec2", region_name=region)
        # check if key pair exists
        kp_exists: bool = False
        kp_list_response = ec2_client.describe_key_pairs(KeyNames=[])
        for kp in kp_list_response['KeyPairs']:
            if kp['KeyName'] == key_name:
                kp_exists = True
                break
        if kp_exists is True:
            if delete_key_pair_if_present is True:
                logger.info(f"key pair {key_name} does exist, going to delete it now")
                ec2_client.delete_key_pair(KeyName=key_name)
            else:
                logger.error(f"key pair {key_name} already exists but delete_key_pair_if_present={delete_key_pair_if_present}, cannot continue")
        else:
            logger.info(f"key pair {key_name} does not exist, going to create it now")
        key_material: Optional[str] = None
        # Create a key pair
        response = ec2_client.create_key_pair(KeyName=key_name)
        if response.get("KeyMaterial") is not None:
            # Extract the private key from the response
            key_material = response["KeyMaterial"]
            logger.info(f"Key {key_name} is created")
        else:
            logger.error(f"Could not create key pair: {key_name}")
    except ClientError as e:
        logger.info(f"Error creating key pair: {e}")
        key_material = None
    return key_material


def get_key_pair(region, config_handler) -> Tuple[str, str]:
    """
    Get or create a key pair for EC2 instances.

    This function handles key pair management by either:
    1. Using an existing key pair file if it exists
    2. Creating a new key pair if enabled and file doesn't exist
    3. Using a pre-existing key pair if generation is disabled

    Args:
        region (str): AWS region where the key pair will be created/used.

    Returns:
        tuple: A tuple containing:
            - str: Path to the private key file (.pem)
            - str: Name of the key pair

    Raises:
        ValueError: If there are errors reading/creating the key pair file
        FileNotFoundError: If key pair file is not found when generation is disabled
        IOError: If there are issues reading/writing the key pair file
    """
    # Create 'key_pair' directory if it doesn't exist
    key_pair_dir = "key_pair"
    if not os.path.exists(key_pair_dir):
        os.makedirs(key_pair_dir)

    # Generate the key pair name using the format: config_name-region
    key_pair_name_configured = config_handler.key_pair.key_pair_name

    # Generate the key pair name using the format: config_name-region
    key_pair_name = f"{key_pair_name_configured}_{region}"
    logger.info(f"key_pair_name_configured={key_pair_name_configured}, setting the key pair name as={key_pair_name}")
    private_key_fname = os.path.join(key_pair_dir, f"{key_pair_name}.pem")

    # Check if key pair generation is enabled
    if config_handler.run_steps.key_pair_generation:
        # First, check if the key pair file already exists
        if os.path.exists(private_key_fname):
            try:
                # If the key pair file exists, read it
                with open(private_key_fname, "r") as file:
                    private_key = file.read()
                print(f"Using existing key pair from {private_key_fname}")
            except IOError as e:
                raise ValueError(
                    f"Error reading existing key pair file '{private_key_fname}': {e}"
                )
        else:
            # If the key pair file doesn't exist, create a new key pair
            try:
                delete_key_pair_if_present: bool = True
                private_key = create_key_pair(key_pair_name, region, delete_key_pair_if_present)
                # Save the key pair to the file
                with open(private_key_fname, "w") as key_file:
                    key_file.write(private_key)

                # Set file permissions to be readable only by the owner
                os.chmod(private_key_fname, 0o400)
                print(
                    f"Key pair '{key_pair_name}' created and saved as '{private_key_fname}'"
                )
            except Exception as e:
                # If key pair creation fails, raise an error
                raise ValueError(f"Failed to create key pair '{key_pair_name}': {e}")
    else:
        # If key pair generation is disabled, attempt to use an existing key
        try:
            with open(private_key_fname, "r") as file:
                private_key = file.read()
            print(f"Using pre-existing key pair from {private_key_fname}")
        except FileNotFoundError:
            raise ValueError(f"Key pair file not found at {private_key_fname}")
        except IOError as e:
            raise ValueError(f"Error reading key pair file '{private_key_fname}': {e}")
    return private_key_fname, key_pair_name
