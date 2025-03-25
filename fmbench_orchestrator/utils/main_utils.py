import os
import re
import time
import json
import wget
import yaml
import boto3
import base64
import urllib
import shutil
import asyncio
import requests
import paramiko
from typing import Dict, Optional, List, Tuple, Any
from fmbench_orchestrator.utils.constants import *
from pathlib import Path
from scp import SCPClient
from jinja2 import Template
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from botocore.exceptions import NoCredentialsError, ClientError
from fmbench_orchestrator.utils.logger import logger

executor = ThreadPoolExecutor()

def get_latest_version(package_name: str = "fmbench") -> Optional[str]:
    url = f"https://pypi.org/pypi/{package_name}/json"
    response = requests.get(url)
    
    if response.status_code == 200:
        data = response.json()
        version = data["info"]["version"]
    else:
        logger.info(f"package '{package_name}' not found on PyPI.")
        version = None
    return version


# Function to check for 'results-*' folders in the root directory of an EC2 instance
from dataclasses import dataclass
from contextlib import contextmanager
from typing import Generator, Optional

@dataclass
class SSHConnectionInfo:
    """Connection information for SSH operations"""
    hostname: str
    username: str
    key_file_path: str
    instance_name: Optional[str] = None

@contextmanager
def ssh_connection(conn_info: SSHConnectionInfo) -> Generator[paramiko.SSHClient, None, None]:
    """Context manager for SSH connections with proper setup and teardown"""
    ssh_client = paramiko.SSHClient()
    ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    private_key = paramiko.RSAKey.from_private_key_file(conn_info.key_file_path)
    
    try:
        ssh_client.connect(conn_info.hostname, username=conn_info.username, pkey=private_key)
        yield ssh_client
    finally:
        ssh_client.close()

def _check_for_results_folder(
    conn_info: SSHConnectionInfo
) -> List:
    """
    Checks if any folder matching the pattern exists in the root directory.

    Args:
        conn_info: SSH connection information

    Returns:
        list: List of matching folder names, or an empty list if none found.
    """
    try:
        # Initialize the result folders within fmbench
        fmbench_result_folders: Optional[List] = None
        
        with ssh_connection(conn_info) as ssh_client:
            logger.info(
                f"_check_for_results_folder, instance_name={conn_info.instance_name}, connected to {conn_info.hostname} as {conn_info.username}"
            )

            # Execute the command to check for folders matching the pattern
            command = f"ls -d {FMBENCH_RESULTS_FOLDER_PATTERN}"
            stdin, stdout, stderr = ssh_client.exec_command(command)
            output = stdout.read().decode().strip()
            error = stderr.read().decode().strip()
            logger.info(
                f"_check_for_results_folder, instance_name={conn_info.instance_name}, output={output}, error={error}"
            )

            if error:
                # No folder found or other errors
                logger.info(
                    f"_check_for_results_folder, instance_name={conn_info.instance_name}, No matching folders found on {conn_info.hostname}: {error}"
                )
                fmbench_result_folders = None
            else:
                # Split the output by newline to get folder names
                fmbench_result_folders = output.split("\n") if output else None
                logger.info(
                    f"_check_for_results_folder, instance_name={conn_info.instance_name}, fmbench_result_folders={fmbench_result_folders}"
                )
    except Exception as e:
        logger.info(f"Error connecting via SSH to {conn_info.hostname}: {e}")
        fmbench_result_folders = None
    return fmbench_result_folders


# Function to retrieve folders from the EC2 instance
from enum import Enum

class TransferDirection(Enum):
    """Enum for file transfer direction"""
    UPLOAD = "upload"
    DOWNLOAD = "download"

def transfer_folder(
    conn_info: SSHConnectionInfo,
    local_folder: str,
    remote_folder: str,
    direction: TransferDirection
) -> bool:
    """
    Transfers a folder between local machine and EC2 instance using SCP.

    Args:
        conn_info: SSH connection information
        local_folder: Local folder path
        remote_folder: Remote folder path
        direction: Whether to upload or download

    Returns:
        bool: True if the folder was transferred successfully
    """
    try:
        with ssh_connection(conn_info) as ssh_client:
            with SCPClient(ssh_client.get_transport()) as scp:
                if direction == TransferDirection.UPLOAD:
                    scp.put(local_folder, remote_path=remote_folder, recursive=True)
                    logger.info(f"Uploaded folder '{local_folder}' to {conn_info.hostname}:{remote_folder}")
                else:
                    scp.get(remote_folder, local_path=local_folder, recursive=True)
                    logger.info(f"Downloaded folder '{remote_folder}' from {conn_info.hostname} to {local_folder}")
                return True
    except Exception as e:
        action = "uploading to" if direction == TransferDirection.UPLOAD else "downloading from"
        logger.error(f"Error {action} {conn_info.hostname} via SCP: {e}")
        return False

def _get_folder_from_instance(
    conn_info: SSHConnectionInfo,
    remote_folder: str,
    local_folder: str,
) -> bool:
    """Retrieves a folder from the EC2 instance to the local machine."""
    return transfer_folder(conn_info, local_folder, remote_folder, TransferDirection.DOWNLOAD)


# Main function to check and retrieve 'results-*' folders from multiple instances
def check_and_retrieve_results_folder(instance: Dict, local_folder_base: str) -> None:
    """
    Checks for 'results-*' folders on a single EC2 instance and retrieves them if found.

    Args:
        instance: Dictionary containing instance details
        local_folder_base: The local base path where the folders should be saved
    """
    try:
        conn_info = SSHConnectionInfo(
            hostname=instance["hostname"],
            username=instance["username"],
            key_file_path=instance["key_file_path"],
            instance_name=instance["instance_name"]
        )
        logger.info(f"check_and_retrieve_results_folder, {conn_info.instance_name}")

        # Check for 'results-*' folders in the specified directory
        results_folders = _check_for_results_folder(conn_info)
        logger.info(
            f"check_and_retrieve_results_folder, {conn_info.instance_name}, result folders {results_folders}"
        )

        # If any folders are found, retrieve them
        for folder in results_folders or []:
            if folder:  # Check if folder name is not empty
                # Create a local folder path for this instance
                local_folder = os.path.join(local_folder_base, conn_info.instance_name)
                logger.info(
                    f"Retrieving folder '{folder}' from {conn_info.instance_name} to '{local_folder}'..."
                )
                _get_folder_from_instance(conn_info, folder, local_folder)
                logger.info(
                    f"check_and_retrieve_results_folder, {conn_info.instance_name}, folder={folder} downloaded"
                )

    except Exception as e:
        logger.error(
            f"Error occurred while attempting to check and retrieve results from the instances: {e}"
        )

def get_fmbench_log(instance: Dict, local_folder_base: str, log_file_path: str, iter_count: int) -> None:
    """
    Retrieves the fmbench log file from an EC2 instance.

    Args:
        instance: Dictionary containing instance details
        local_folder_base: The local base path where logs should be saved
        log_file_path: The remote path to the log file
        iter_count: The iteration number for the log file
    """
    conn_info = SSHConnectionInfo(
        hostname=instance["hostname"],
        username=instance["username"],
        key_file_path=instance["key_file_path"],
        instance_name=instance["instance_name"]
    )
    
    formatted_log_path = log_file_path.format(username=conn_info.username)
    local_folder = os.path.join(local_folder_base, conn_info.instance_name)
    local_log_file = os.path.join(local_folder, f'fmbench_{iter_count}.log')

    try:
        # Clear out the local folder if it exists on first iteration
        if Path(local_folder).is_dir() and iter_count == 1:
            logger.info(f"going to delete {local_folder}, iter_count={iter_count}")
            shutil.rmtree(local_folder)
        os.makedirs(local_folder, exist_ok=True)

        # Download log file using SFTP
        with ssh_connection(conn_info) as ssh_client:
            with ssh_client.open_sftp() as sftp:
                sftp.get(formatted_log_path, local_log_file)
                logger.info(f"Downloaded '{formatted_log_path}' to '{local_log_file}'")

    except Exception as e:
        logger.error(f"Error occurred while retrieving the log file from {conn_info.instance_name}: {e}")


#Rewrite this function to just get back the instance details.

def generate_instance_details(instance_id_list, instance_data_map):
    """
    Generates a list of instance details dictionaries containing hostname, username, and key file path.

    Args:
        instance_id_list (list): List of EC2 instance IDs.
        instance_data_map (dict) : Dict of all neccessary fields

    Returns:
        list: A list of dictionaries containing hostname, username, and key file path for each instance.
    """
    instance_details = []

    for instance_id in instance_id_list:

        # If a config entry is found, get the config path
        # Directly access the instance_data_map using the instance_id
        config_entry = instance_data_map.get(instance_id, None)

        # If no config entry is found, raise an exception
        if not config_entry:
            raise ValueError(f"Configuration not found for instance ID: {instance_id}")

        # Check if all required fields are present, raise a ValueError if any are missing
        required_fields = [
            "fmbench_config",
            "post_startup_script",
            "fmbench_complete_timeout",
            "region",
            "PRIVATE_KEY_FNAME",
        ]

        missing_fields = [
            field
            for field in required_fields
            if field not in config_entry or config_entry[field] is None
        ]

        if missing_fields:
            raise ValueError(
                f"Missing configuration fields for instance ID {instance_id}: {', '.join(missing_fields)}"
            )

        # Extract all the necessary configuration values from the config entry
        fmbench_config = config_entry["fmbench_config"]
        post_startup_script = config_entry["post_startup_script"]
        upload_files = config_entry.get("upload_files")
        post_startup_script_params = config_entry.get("post_startup_script_params")
        fmbench_complete_timeout = config_entry["fmbench_complete_timeout"]
        region = config_entry["region"]
        PRIVATE_KEY_FNAME = config_entry["PRIVATE_KEY_FNAME"]


        # Get the public hostname and username for each instance
        public_hostname, username, instance_name = _get_ec2_hostname_and_username(
            instance_id, region, public_dns=True
        )

        # Append the instance details to the list if hostname and username are found
        if public_hostname and username:
            instance_details.append(
                {
                    "instance_id": instance_id,
                    "instance_name": instance_name,
                    "hostname": public_hostname,
                    "username": username,
                    "key_file_path": (
                        f"{PRIVATE_KEY_FNAME}.pem"
                        if not PRIVATE_KEY_FNAME.endswith(".pem")
                        else PRIVATE_KEY_FNAME
                    ),
                    "config_file": fmbench_config,
                    "post_startup_script": post_startup_script,
                    "post_startup_script_params" : post_startup_script_params,
                    "upload_files": upload_files,
                    "fmbench_complete_timeout": fmbench_complete_timeout,
                    "region": config_entry.get("region", "us-east-1"),
                }
            )
        else:
            logger.error(
                f"Failed to retrieve hostname and username for instance {instance_id}"
            )
    return instance_details

def run_command_on_instances(
    instances: List[Dict],
    command: str
) -> Dict:
    """
    Executes a command on multiple EC2 instances using the instance_details list.

    Args:
        instances: List of dictionaries containing instance details
        command: The command to execute on each instance

    Returns:
        dict: A dictionary containing the results of command execution for each instance.
              The key is the instance's hostname, and the value is a dictionary with
              'stdout', 'stderr', and 'exit_status'.
    """
    results: Dict = {}

    for instance in instances:
        conn_info = SSHConnectionInfo(
            hostname=instance["hostname"],
            username=instance["username"],
            key_file_path=instance["key_file_path"],
            instance_name=instance["instance_name"]
        )
        logger.info(f"Running command on {conn_info.instance_name}, {conn_info.hostname} as {conn_info.username}...")

        try:
            with ssh_connection(conn_info) as ssh_client:
                logger.info(f"Connected to {conn_info.hostname} as {conn_info.username}")
                stdin, stdout, stderr = ssh_client.exec_command(command)
                exit_status = stdout.channel.recv_exit_status()
                results[conn_info.hostname] = {
                    "stdout": stdout.read().decode(),
                    "stderr": stderr.read().decode(),
                    "exit_status": exit_status,
                }
        except Exception as e:
            logger.error(f"Error connecting to {conn_info.hostname} or executing command: {e}")
            results[conn_info.hostname] = {
                "stdout": "",
                "stderr": str(e),
                "exit_status": -1
            }
    return results
    return results

def upload_and_execute_script_invoke_shell(
    conn_info: SSHConnectionInfo,
    script_content: str,
    remote_script_path: str,
) -> str:
    """
    Uploads a bash script to the EC2 instance and executes it via an interactive SSH shell.

    Args:
        conn_info: SSH connection information
        script_content: The content of the bash script to upload
        remote_script_path: The remote path where the script should be saved

    Returns:
        str: The output of the executed script.
    """
    output: str = ""
    try:
        with ssh_connection(conn_info) as ssh_client:
            logger.info(f"Connected to {conn_info.hostname} as {conn_info.username}")
            formatted_path = remote_script_path.format(username=conn_info.username)
            
            # Upload script using SFTP
            try:
                with ssh_client.open_sftp() as sftp:
                    with sftp.file(formatted_path, "w") as remote_file:
                        remote_file.write(script_content)
                    logger.info(f"Script successfully uploaded to {formatted_path}")
            except Exception as e:
                logger.error(f"Failed to upload script to {formatted_path}: {e}")
                return output

            # Execute script using interactive shell
            with ssh_client.invoke_shell() as shell:
                time.sleep(1)  # Initialize shell

                logger.info("Checking for and removing existing FMBench complete flag")
                shell.send("if [ -f /tmp/fmbench_completed.flag ]; then rm /tmp/fmbench_completed.flag; fi\n")
                time.sleep(1)

                shell.send(f"chmod +x {formatted_path}\n")
                time.sleep(1)

                shell.send(
                    f"nohup bash {formatted_path} > $HOME/run_fmbench_nohup.log 2>&1 & disown\n"
                )
                time.sleep(1)

                while shell.recv_ready():
                    output += shell.recv(1024).decode("utf-8")
                    time.sleep(2)

    except Exception as e:
        logger.error(f"Error connecting via SSH to {conn_info.hostname}: {e}")
        output = ""
    return output
    return output


# Asynchronous function to download a configuration file if it is a URL
async def download_config_async(url, download_dir=DOWNLOAD_DIR_FOR_CFG_FILES):
    """Asynchronously downloads the configuration file from a URL."""
    os.makedirs(download_dir, exist_ok=True)
    local_path = os.path.join(download_dir, os.path.basename(url))
    if os.path.exists(local_path):
        logger.info(
            f"{local_path} already existed, deleting it first before downloading again"
        )
        os.remove(local_path)
    # Run the blocking download operation in a separate thread
    await asyncio.get_event_loop().run_in_executor(
        executor, wget.download, url, local_path
    )
    return local_path


async def upload_file_to_instance_async(
    hostname, username, key_file_path, file_paths
):
    """Asynchronously uploads multiple files to the EC2 instance."""
    
    def upload_files():
        # Initialize the SSH client
        ssh_client = paramiko.SSHClient()
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        # Load the private key
        private_key = paramiko.RSAKey.from_private_key_file(key_file_path)

        # Connect to the instance
        ssh_client.connect(hostname, username=username, pkey=private_key)
        logger.info(f"Connected to {hostname} as {username}")

        # Upload the files
        with SCPClient(ssh_client.get_transport()) as scp:
            for file_path in file_paths:
                local_path = file_path['local']
                remote_path = file_path['remote']
                scp.put(local_path, remote_path)
                logger.info(f"Uploaded {local_path} to {hostname}:{remote_path}")

        # Close the SSH connection
        ssh_client.close()

    # Run the blocking operation in a separate thread
    await asyncio.to_thread(upload_files)

# Asynchronous function to handle the configuration file
async def handle_config_file_async(instance, config_file):
    """Handles downloading and uploading of the config file based on the config type (URL or local path)."""
    
    config_path = config_file
    file_paths = []
    
    # Check if the config path is a URL
    if urllib.parse.urlparse(config_path).scheme in ("http", "https"):
        logger.info(f"Config is a URL. Downloading from {config_path}...")
        local_config_path = await download_config_async(config_path)
    else:
        # It's a local file path, use it directly
        local_config_path = config_path

    # Define the remote path for the configuration file on the EC2 instance
    remote_config_path = f"/home/{instance['username']}/{os.path.basename(local_config_path)}"
    logger.info(f"remote_config_path is: {remote_config_path}...")

    # Append the local and remote paths to the list of files to upload
    file_paths.append({'local': local_config_path, 'remote': remote_config_path})

    # Upload the configuration file to the EC2 instance
    await upload_file_to_instance_async(
        instance["hostname"],
        instance["username"],
        instance["key_file_path"],
        file_paths  # Now passing the list of dictionaries with local and remote paths
    )

    return remote_config_path

def _check_completion_flag(
    conn_info: SSHConnectionInfo,
    flag_file_path: str = STARTUP_COMPLETE_FLAG_FPATH
) -> bool:
    """
    Checks if the startup flag file exists on the EC2 instance.

    Args:
        conn_info: SSH connection information
        flag_file_path: Path to the startup flag file on the instance

    Returns:
        bool: True if the flag file exists, False otherwise.
    """
    try:
        with ssh_connection(conn_info) as ssh_client:
            stdin, stdout, stderr = ssh_client.exec_command(
                f"test -f {flag_file_path} && echo 'File exists'"
            )
            output = stdout.read().decode().strip()
            return output == "File exists"
    except Exception as e:
        logger.info(f"Error connecting via SSH to {conn_info.hostname}: {e}")
        return False
        return False


def wait_for_flag(
    instance,
    flag_file_path,
    log_file_path,
    max_wait_time=MAX_WAIT_TIME_FOR_STARTUP_SCRIPT_IN_SECONDS,
    check_interval=SCRIPT_CHECK_INTERVAL_IN_SECONDS,
) -> bool:
    """
    Waits for the startup flag file on the EC2 instance, and returns the script if the flag file is found.

    Args:
        instance (dict): The dictionary containing instance details (hostname, username, key_file_path).
        formatted_script (str): The bash script content to be executed.
        remote_script_path (str): The remote path where the script should be saved on the instance.
        max_wait_time (int): Maximum wait time in seconds (default: 600 seconds or 10 minutes).
        check_interval (int): Interval time in seconds between checks (default: 30 seconds).
    """
    end_time = time.time() + max_wait_time
    startup_complete: bool = False
    logger.info(
        f"going to wait {max_wait_time}s for the startup script for {instance['instance_name']} to complete"
    )
    logger.info(
        "-----------------------------------------------------------------------------------------------"
    )
    logger.info(
        f"you can open another terminal and see the startup logs from this machine using the following command"
    )
    logger.info(
        f"ssh -i {instance['key_file_path']} {instance['username']}@{instance['hostname']} 'tail -f {log_file_path}'"
    )
    logger.info(
        "-----------------------------------------------------------------------------------------------"
    )
    while time.time() < end_time:
        completed = _check_completion_flag(
            hostname=instance["hostname"],
            username=instance["username"],
            key_file_path=instance["key_file_path"],
            flag_file_path=flag_file_path,
        )
        if completed is True:
            logger.info(f"{flag_file_path} flag file found!!")
            break
        else:
            time_remaining = end_time - time.time()
            logger.warning(
                f"Waiting for {flag_file_path}, instance_name={instance['instance_name']}..., seconds until timeout={int(time_remaining)}s"
            )
            time.sleep(check_interval)
    logger.error(
        f"max_wait_time={max_wait_time} expired and the script for {instance['hostname']} has still not completed, exiting, "
    )
    return completed


# Function to upload folders to the EC2 instance
def _put_folder_to_instance(
    conn_info: SSHConnectionInfo,
    local_folder: str,
    remote_folder: str,
) -> bool:
    """Uploads a folder from the local machine to the EC2 instance."""
    return transfer_folder(conn_info, local_folder, remote_folder, TransferDirection.UPLOAD)
