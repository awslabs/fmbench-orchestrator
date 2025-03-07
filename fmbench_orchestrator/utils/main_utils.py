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
def _check_for_results_folder(
    hostname: str, instance_name: str, username: str, key_file_path: str
) -> List:
    """
    Checks if any folder matching the pattern exists in the root directory.

    Args:
        hostname (str): The public IP or DNS of the EC2 instance.
        username (str): The SSH username (e.g., 'ec2-user').
        key_file_path (str): The path to the PEM key file.
        folder_pattern (str): The pattern to match folders (default is '/results-*').

    Returns:
        list: List of matching folder names, or an empty list if none found.
    """
    try:
        # Initialize the result folders within fmbench
        fmbench_result_folders: Optional[List] = None
        # Initialize the SSH client
        ssh_client = paramiko.SSHClient()
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        # Load the private key
        private_key = paramiko.RSAKey.from_private_key_file(key_file_path)

        # Connect to the instance
        ssh_client.connect(hostname, username=username, pkey=private_key)
        logger.info(
            f"_check_for_results_folder, instance_name={instance_name}, connected to {hostname} as {username}"
        )

        # Execute the command to check for folders matching the pattern
        command = f"ls -d {FMBENCH_RESULTS_FOLDER_PATTERN}"
        stdin, stdout, stderr = ssh_client.exec_command(command)
        output = stdout.read().decode().strip()
        error = stderr.read().decode().strip()
        logger.info(
            f"_check_for_results_folder, instance_name={instance_name}, output={output}, error={error}"
        )
        # Close the connection
        ssh_client.close()
        if error:
            # No folder found or other errors
            logger.info(
                f"_check_for_results_folder, instance_name={instance_name}, No matching folders found on {hostname}: {error}"
            )
            fmbench_result_folders = None
        else:
            # Split the output by newline to get folder names
            fmbench_result_folders = output.split("\n") if output else None
            logger.info(
                f"_check_for_results_folder, instance_name={instance_name}, fmbench_result_folders={fmbench_result_folders}"
            )
    except Exception as e:
        logger.info(f"Error connecting via SSH to {hostname}: {e}")
        fmbench_result_folders = None
    return fmbench_result_folders


# Function to retrieve folders from the EC2 instance
def _get_folder_from_instance(
    hostname: str,
    username: str,
    key_file_path: str,
    remote_folder: str,
    local_folder: str,
) -> bool:
    """
    Retrieves a folder from the EC2 instance to the local machine using SCP.

    Args:
        hostname (str): The public IP or DNS of the EC2 instance.
        username (str): The SSH username (e.g., 'ec2-user').
        key_file_path (str): The path to the PEM key file.
        remote_folder (str): The path of the folder on the EC2 instance to retrieve.
        local_folder (str): The local path where the folder should be saved.

    Returns:
        bool: True if the folder was retrieved successfully, False otherwise.
    """
    try:
        folder_retrieved: bool = False
        # Initialize the SSH client
        ssh_client = paramiko.SSHClient()
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        # Load the private key
        private_key = paramiko.RSAKey.from_private_key_file(key_file_path)

        # Connect to the instance
        ssh_client.connect(hostname, username=username, pkey=private_key)

        # Use SCP to copy the folder
        with SCPClient(ssh_client.get_transport()) as scp:
            scp.get(remote_folder, local_path=local_folder, recursive=True)
        logger.info(
            f"Folder '{remote_folder}' retrieved successfully to '{local_folder}'."
        )
        # Close the connection
        ssh_client.close()
        folder_retrieved = True
    except Exception as e:
        logger.error(f"Error retrieving folder from {hostname} via SCP: {e}")
        folder_retrieved = False
    return folder_retrieved


# Main function to check and retrieve 'results-*' folders from multiple instances
def check_and_retrieve_results_folder(instance: Dict, local_folder_base: str):
    """
    Checks for 'results-*' folders on a single EC2 instance and retrieves them if found.

    Args:
        instance (dict): Dictionary containing instance details (hostname, username, instance_id).
        local_folder_base (str): The local base path where the folders should be saved.

    Returns:
        None
    """
    try:
        hostname = instance["hostname"]
        instance_name = instance["instance_name"]
        username = instance["username"]
        key_file_path = instance["key_file_path"]
        instance_id = instance["instance_id"]
        logger.info(f"check_and_retrieve_results_folder, {instance['instance_name']}")
        # Check for 'results-*' folders in the specified directory
        results_folders = _check_for_results_folder(
            hostname, instance_name, username, key_file_path
        )
        logger.info(
            f"check_and_retrieve_results_folder, {instance_name}, result folders {results_folders}"
        )
        # If any folders are found, retrieve them
        for folder in results_folders:
            if folder:  # Check if folder name is not empty
                # Create a local folder path for this instance
                local_folder = os.path.join(local_folder_base, instance_name)
                logger.info(
                    f"Retrieving folder '{folder}' from {instance_name} to '{local_folder}'..."
                )
                _get_folder_from_instance(
                    hostname, username, key_file_path, folder, local_folder
                )
                logger.info(
                    f"check_and_retrieve_results_folder, {instance_name}, folder={folder} downloaded"
                )

    except Exception as e:
        logger.error(
            f"Error occured while attempting to check and retrieve results from the instances: {e}"
        )

def get_fmbench_log(instance: Dict, local_folder_base: str, log_file_path: str, iter_count: int):
    """
    Checks for 'fmbench.log' file on a single EC2 instance and retrieves them if found.

    Args:
        instance (dict): Dictionary containing instance details (hostname, username, instance_id, key_file_path).
        local_folder_base (str): The local base path where the folders should be saved.
        log_file_path (str): The remote path to the log file.

    Returns:
        None
    """
    hostname = instance["hostname"]
    username = instance["username"]
    key_file_path = instance["key_file_path"]
    instance_name = instance["instance_name"]
    log_file_path = log_file_path.format(username=username)
    # Define local folder to store the log file
    local_folder = os.path.join(local_folder_base, instance_name)
    local_log_file = os.path.join(local_folder, f'fmbench_{iter_count}.log')

    try:
        # Clear out the local folder if it exists, then recreate it
        if Path(local_folder).is_dir() and iter_count == 1:
            logger.info(f"going to delete {local_folder}, iter_count={iter_count}")
            shutil.rmtree(local_folder)
        os.makedirs(local_folder, exist_ok=True)

        # Setup SSH and SFTP connection using Paramiko
        key = paramiko.RSAKey.from_private_key_file(key_file_path)
        ssh_client = paramiko.SSHClient()
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh_client.connect(hostname=hostname, username=username, pkey=key)

        # Use SFTP to download the log file
        sftp = ssh_client.open_sftp()
        sftp.get(log_file_path, local_log_file)
        logger.info(f"Downloaded '{log_file_path}' to '{local_log_file}'")

        # Close connections
        sftp.close()
        ssh_client.close()

    except Exception as e:
        logger.error(f"Error occurred while retrieving the log file from {instance_name}: {e}")


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
    instance_details: List, key_file_path: str, command: str
) -> Dict:
    """
    Executes a command on multiple EC2 instances using the instance_details list.

    Args:
        instance_details (list): List of dictionaries containing instance details (hostname, username, key_file_path).
        command (str): The command to execute on each instance.
        key_file_path (str): Path to the pem key file

    Returns:
        dict: A dictionary containing the results of command execution for each instance.
              The key is the instance's hostname, and the value is a dictionary with 'stdout', 'stderr', and 'exit_status'.
    """
    results: Dict = {}

    for instance in instance_details:
        hostname, username, instance_name = (
            instance["hostname"],
            instance["username"],
            instance["instance_name"],
        )
        logger.info(f"Running command on {instance_name}, {hostname} as {username}...")
        try:
            with paramiko.SSHClient() as ssh_client:
                ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                private_key = paramiko.RSAKey.from_private_key_file(key_file_path)
                ssh_client.connect(hostname, username=username, pkey=private_key)
                logger.info(f"Connected to {hostname} as {username}")
                stdin, stdout, stderr = ssh_client.exec_command(command)
                # Wait for the command to complete
                exit_status = stdout.channel.recv_exit_status()
                results[hostname] = {
                    "stdout": stdout.read().decode(),
                    "stderr": stderr.read().decode(),
                    "exit_status": exit_status,
                }
        except Exception as e:
            logger.error(f"Error connecting to {hostname} or executing command: {e}")
            results[hostname] = {"stdout": "", "stderr": str(e), "exit_status": -1}
    return results


def upload_and_execute_script_invoke_shell(
    hostname: str,
    username: str,
    key_file_path: str,
    script_content: str,
    remote_script_path,
) -> str:
    """
    Uploads a bash script to the EC2 instance and executes it via an interactive SSH shell.

    Args:
        hostname (str): The public IP or DNS of the EC2 instance.
        username (str): The SSH username (e.g., 'ubuntu').
        key_file_path (str): The path to the PEM key file.
        script_content (str): The content of the bash script to upload.
        remote_script_path (str): The remote path where the script should be saved on the instance.

    Returns:
        str: The output of the executed script.
    """
    # Initialize the output
    output: str = ""
    try:
        with paramiko.SSHClient() as ssh_client:
            ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            private_key = paramiko.RSAKey.from_private_key_file(key_file_path)
            ssh_client.connect(hostname, username=username, pkey=private_key)
            logger.info(f"Connected to {hostname} as {username}")
            remote_script_path = remote_script_path.format(username=username)
            try:
                with ssh_client.open_sftp() as sftp:
                    with sftp.file(remote_script_path, "w") as remote_file:
                        remote_file.write(script_content)
                    logger.info(f"Script successfully uploaded to {remote_script_path}")
            except Exception as e:
                logger.error(f"Failed to upload script to {remote_script_path}: {e}")


            with ssh_client.invoke_shell() as shell:
                time.sleep(1)  # Give the shell some time to initialize

                logger.info("Going to check if FMBench complete Flag exists in this instance, if it does, remove it")
                # Check if fmbench flag exists, if it does, remove it:
                shell.send("if [ -f /tmp/fmbench_completed.flag ]; then rm /tmp/fmbench_completed.flag; fi\n")
                
                time.sleep(1)

                shell.send(f"chmod +x {remote_script_path}\n")
                time.sleep(1)  # Wait for the command to complete

                shell.send(
                    f"nohup bash {remote_script_path} > $HOME/run_fmbench_nohup.log 2>&1 & disown\n"
                )
                time.sleep(1)  # Wait for the command to complete

                while shell.recv_ready():
                    output += shell.recv(1024).decode("utf-8")
                    time.sleep(2)  # Allow time for the command output to be captured
                # Close the shell and connection
                shell.close()
                ssh_client.close()
    except Exception as e:
        logger.error(f"Error connecting via SSH to {hostname}: {e}")
        output = ""
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
    hostname, username, key_file_path, flag_file_path=STARTUP_COMPLETE_FLAG_FPATH
):
    """
    Checks if the startup flag file exists on the EC2 instance.

    Args:
        hostname (str): The public IP or DNS of the EC2 instance.
        username (str): The SSH username (e.g., 'ubuntu').
        key_file_path (str): The path to the PEM key file.
        flag_file_path (str): The path to the startup flag file on the instance. Default is '/tmp/startup_complete.flag'.

    Returns:
        bool: True if the flag file exists, False otherwise.
    """
    try:
        # Initialize the SSH client
        ssh_client = paramiko.SSHClient()
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        # Load the private key
        private_key = paramiko.RSAKey.from_private_key_file(key_file_path)

        # Connect to the instance
        ssh_client.connect(hostname, username=username, pkey=private_key)

        # Check if the flag file exists
        stdin, stdout, stderr = ssh_client.exec_command(
            f"test -f {flag_file_path} && echo 'File exists'"
        )
        output = stdout.read().decode().strip()
        error = stderr.read().decode().strip()

        # Close the connection
        ssh_client.close()

        # Return True if the file exists, otherwise False
        return output == "File exists"

    except Exception as e:
        logger.info(f"Error connecting via SSH to {hostname}: {e}")
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
    hostname: str,
    username: str,
    key_file_path: str,
    local_folder: str,
    remote_folder: str,
) -> bool:
    """
    Uploads a folder from the local machine to the EC2 instance using SCP.

    Args:
        hostname (str): The public IP or DNS of the EC2 instance.
        username (str): The SSH username (e.g., 'ec2-user').
        key_file_path (str): The path to the PEM key file.
        local_folder (str): The local path of the folder to upload.
        remote_folder (str): The path on the EC2 instance where the folder should be saved.

    Returns:
        bool: True if the folder was uploaded successfully, False otherwise.
    """
    try:
        folder_uploaded: bool = False
        # Initialize the SSH client
        ssh_client = paramiko.SSHClient()
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        # Load the private key
        private_key = paramiko.RSAKey.from_private_key_file(key_file_path)

        # Connect to the instance
        ssh_client.connect(hostname, username=username, pkey=private_key)

        # Use SCP to copy the folder
        with SCPClient(ssh_client.get_transport()) as scp:
            scp.put(local_folder, remote_path=remote_folder, recursive=True)
        logger.info(
            f"Folder '{local_folder}' uploaded successfully to '{remote_folder}'."
        )
        # Close the connection
        ssh_client.close()
        folder_uploaded = True
    except Exception as e:
        logger.error(f"Error uploading folder to {hostname} via SCP: {e}")
        folder_uploaded = False
    return folder_uploaded
