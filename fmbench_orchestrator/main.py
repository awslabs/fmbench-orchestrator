import os
import sys
import time
import json
import wget
import yaml
import boto3
import base64
import urllib
import logging
import asyncio
import argparse
import paramiko
import socket
from fmbench_orchestrator.utils import *
from fmbench_orchestrator.utils.constants import *
import fmbench_orchestrator.globals as globals
from pathlib import Path
from scp import SCPClient
from typing import Optional, List, Dict
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from botocore.exceptions import NoCredentialsError, ClientError
from fmbench_orchestrator.cli import parse_args
from fmbench_orchestrator.utils.logger import logger
from fmbench_orchestrator.globals import (
    create_iam_instance_profile_arn,
    get_iam_role,
    get_sg_id,
    get_key_pair,
    upload_and_run_script,
)

from fmbench_orchestrator.schema.handler import ConfigHandler
from fmbench_orchestrator.instance_handler import InstanceHandler


executor = ThreadPoolExecutor()

# Initialize global variables for this file
instance_id_list: List = []
fmbench_config_map: List = []
fmbench_post_startup_script_map: List = []
instance_data_map: Dict = {}


async def execute_fmbench(instance, post_install_script, remote_script_path):
    """
    Asynchronous wrapper for deploying an instance using synchronous functions.
    """
    # Check for the startup completion flag
    startup_complete = await asyncio.get_event_loop().run_in_executor(
        executor,
        wait_for_flag,
        instance,
        STARTUP_COMPLETE_FLAG_FPATH,
        CLOUD_INITLOG_PATH,
    )

    if startup_complete:
        if instance["upload_files"]:
            await upload_file_to_instance_async(
                instance["hostname"],
                instance["username"],
                instance["key_file_path"],
                file_paths=instance["upload_files"],
            )
        num_configs: int = len(instance["config_file"])
        for cfg_idx, config_file in enumerate(instance["config_file"]):
            cfg_idx += 1
            instance_name = instance["instance_name"]
            local_mode_param = POST_STARTUP_LOCAL_MODE_VAR
            write_bucket_param = POST_STARTUP_WRITE_BUCKET_VAR
            # If a user has provided the additional generatic command line arguments, those will
            # be used in the fmbench --config-file command. Such as the model id, the instance type,
            # the serving properties, etc.
            additional_args = ""

            logger.info(
                f"going to run config {cfg_idx} of {num_configs} for instance {instance_name}"
            )
            # Handle configuration file (download/upload) and get the remote path
            remote_config_path = await handle_config_file_async(instance, config_file)
            # Format the script with the remote config file path
            # Change this later to be a better implementation, right now it is bad.

            # override defaults for post install script params if specified
            pssp = instance.get("post_startup_script_params")
            logger.info(f"User provided post start up script parameters: {pssp}")
            if pssp is not None:
                local_mode_param = pssp.get("local_mode", local_mode_param)
                write_bucket_param = pssp.get("write_bucket", write_bucket_param)
                additional_args = pssp.get("additional_args", additional_args)
            logger.info(
                f"Going to use the additional arguments in the command line: {additional_args}"
            )

            # Convert `local_mode_param` to "yes" or "no" if it is a boolean
            if isinstance(local_mode_param, bool):
                local_mode_param = "yes" if local_mode_param else "no"

            formatted_script = (
                Path(post_install_script)
                .read_text()
                .format(
                    config_file=remote_config_path,
                    local_mode=local_mode_param,
                    write_bucket=write_bucket_param,
                    additional_args=additional_args,
                )
            )
            logger.info(f"Formatted post startup script: {formatted_script}")

            # Upload and execute the script on the instance
            retries = 0
            max_retries = 2
            retry_sleep = 60
            while True:
                logger.info("Startup Script complete, executing fmbench now")
                script_output = await asyncio.get_event_loop().run_in_executor(
                    executor,
                    upload_and_execute_script_invoke_shell,
                    instance["hostname"],
                    instance["username"],
                    instance["key_file_path"],
                    formatted_script,
                    remote_script_path,
                )
                logger.info(
                    f"Script Output from {instance['hostname']}:\n{script_output}"
                )
                if script_output != "":
                    break
                else:
                    logger.error(f"post startup script not successfull after {retries}")
                    if retries < max_retries:
                        logger.error(
                            f"post startup script retries={retries}, trying after a {retry_sleep}s sleep"
                        )
                    else:
                        logger.error(
                            f"post startup script retries={retries}, not retrying any more, benchmarking "
                            f"for instance={instance} will fail...."
                        )
                        break
                time.sleep(retry_sleep)
                retries += 1

            # Check for the fmbench completion flag
            fmbench_complete = await asyncio.get_event_loop().run_in_executor(
                executor,
                wait_for_flag,
                instance,
                FMBENCH_TEST_COMPLETE_FLAG_FPATH,
                FMBENCH_LOG_PATH,
                instance["fmbench_complete_timeout"],
                SCRIPT_CHECK_INTERVAL_IN_SECONDS,
            )

            logger.info("Going to get fmbench.log from the instance now")
            results_folder = os.path.join(
                RESULTS_DIR, globals.config_data["general"]["name"]
            )
            # Get Log even if fmbench_completes or not
            await asyncio.get_event_loop().run_in_executor(
                executor,
                get_fmbench_log,
                instance,
                results_folder,
                FMBENCH_LOG_REMOTE_PATH,
                cfg_idx,
            )

            if fmbench_complete:
                logger.info("Fmbench Run successful, Getting the folders now")
                await asyncio.get_event_loop().run_in_executor(
                    executor,
                    check_and_retrieve_results_folder,
                    instance,
                    results_folder,
                )
        if globals.config_data["run_steps"]["delete_ec2_instance"]:
            delete_ec2_instance(instance["instance_id"], instance["region"])
            instance_id_list.remove(instance["instance_id"])


async def multi_deploy_fmbench(instance_details, remote_script_path):
    tasks = []

    # Create a task for each instance
    for instance in instance_details:
        # Make this async as well?
        # Format the script with the specific config file
        logger.info(f"Instance Details are: {instance}")
        # Create an async task for this instance
        tasks.append(
            execute_fmbench(
                instance, instance["post_startup_script"], remote_script_path
            )
        )

    # Run all tasks concurrently
    await asyncio.gather(*tasks)


async def deploy_benchmarking(instance_details, config_handler):
    """
    Deploy benchmarking tasks to instances.

    Args:
        instance_details (List[Dict]): List of instance details from InstanceDetails models
        config_handler (ConfigHandler): Configuration handler instance
    """
    tasks = []
    for instance_detail in instance_details:
        tasks.append(
            asyncio.create_task(execute_fmbench(instance_detail, config_handler))
        )
    await asyncio.gather(*tasks)


async def run_benchmark(public_ip, instance_detail):
    """
    Run the benchmark on a remote instance.

    Args:
        public_ip (str): Public IP address of the instance
        instance_detail (Dict): Instance details from InstanceDetails model
    """
    # Create SSH client
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        # Connect to instance
        ssh.connect(
            public_ip, username="ubuntu", key_filename=instance_detail["key_path"]
        )

        # Execute benchmark commands
        commands = [
            f"cd {instance_detail['fmbench_repo']}",
            "source venv/bin/activate",
            f"python -m fmbench.run --config {instance_detail['fmbench_config']}",
        ]

        for cmd in commands:
            logger.info(f"Running command: {cmd}")
            stdin, stdout, stderr = ssh.exec_command(cmd)
            exit_status = stdout.channel.recv_exit_status()

            if exit_status != 0:
                error = stderr.read().decode()
                logger.error(f"Command failed with status {exit_status}: {error}")
                raise RuntimeError(f"Benchmark command failed: {cmd}")

            output = stdout.read().decode()
            logger.info(f"Command output: {output}")

    except Exception as e:
        logger.error(f"Error running benchmark on {public_ip}: {e}")
        raise
    finally:
        ssh.close()


async def wait_for_ssh(public_ip, max_retries=30, delay=10):
    """
    Wait for SSH to become available on the instance.

    Args:
        public_ip (str): Public IP address of the instance
        max_retries (int): Maximum number of retry attempts
        delay (int): Delay between retries in seconds
    """
    for attempt in range(max_retries):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            result = sock.connect_ex((public_ip, 22))
            sock.close()

            if result == 0:
                logger.info(f"SSH is available on {public_ip}")
                return
        except Exception as e:
            logger.debug(f"SSH check failed: {e}")

        logger.info(
            f"Waiting for SSH on {public_ip}, attempt {attempt + 1}/{max_retries}"
        )
        await asyncio.sleep(delay)

    raise TimeoutError(f"SSH did not become available on {public_ip}")


def cli_main():
    args = parse_args()
    logger.info(f"main, {args} = args")

    config_handler = ConfigHandler.from_args(
        config_file=args.config_file,
        ami_mapping_file=args.ami_mapping_file,
        fmbench_config_file=args.fmbench_config_file,
        infra_config_file=args.infra_config_file,
        write_bucket=args.write_bucket,
    ).load_config()

    logger.info(
        f"Loaded Config {json.dumps(config_handler.config.model_dump(mode='json'), indent=2)}"
    )

    try:
        hf_token = config_handler.get_hf_token()
        logger.info("Successfully loaded Hugging Face token")
    except Exception as e:
        logger.error(f"Failed to load Hugging Face token: {e}")
        sys.exit(1)

    for instance in config_handler.instances:
        logger.info(f"Instance list is as follows: {instance.model_dump(mode='json')}")

    # Initialize and use the InstanceHandler
    instance_handler = InstanceHandler(config_handler=config_handler)
    instance_id_list, instance_data_map = instance_handler.deploy_instances(args)
    instance_handler.wait_for_instances()

    # Generate instance details from the Pydantic models
    instance_details = [
        details.model_dump()
        for details in instance_handler.instance_details_map.values()
    ]

    asyncio.run(
        deploy_benchmarking(instance_details, config_handler)
    )  # This is the correct way to run the async main
    logger.info("all done")


if __name__ == "__main__":
    cli_main()
