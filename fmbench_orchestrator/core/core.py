import os
import time
import asyncio
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict
from fmbench_orchestrator.utils.logger import logger
from fmbench_orchestrator.utils.constants import *
from fmbench_orchestrator.utils.main_utils import (
    wait_for_flag,
    upload_file_to_instance_async,
    handle_config_file_async,
    upload_and_execute_script_invoke_shell,
    get_fmbench_log,
    check_and_retrieve_results_folder,
)
from fmbench_orchestrator.aws.ec2 import delete_ec2_instance

class BenchmarkRunner:
    def __init__(self):
        self.executor = ThreadPoolExecutor()
        self.instance_id_list: List = []

    async def execute_fmbench(self, instance, post_install_script, remote_script_path):
        """
        Asynchronous wrapper for deploying an instance using synchronous functions.
        """
        # Check for the startup completion flag
        startup_complete = await asyncio.get_event_loop().run_in_executor(
            self.executor,
            wait_for_flag,
            instance,
            CONSTANTS.STARTUP_COMPLETE_FLAG_FPATH,
            CONSTANTS.CLOUD_INITLOG_PATH,
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
                        self.executor,
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
                    self.executor,
                    wait_for_flag,
                    instance,
                    CONSTANTS.FMBENCH_TEST_COMPLETE_FLAG_FPATH,
                    CONSTANTS.FMBENCH_LOG_PATH,
                    instance["fmbench_complete_timeout"],
                    CONSTANTS.SCRIPT_CHECK_INTERVAL_IN_SECONDS,
                )

                logger.info("Going to get fmbench.log from the instance now")
                results_folder = os.path.join(
                    CONSTANTS.RESULTS_DIR, globals.config_data["general"]["name"]
                )
                # Get Log even if fmbench_completes or not
                await asyncio.get_event_loop().run_in_executor(
                    self.executor,
                    get_fmbench_log,
                    instance,
                    results_folder,
                    CONSTANTS.FMBENCH_LOG_REMOTE_PATH,
                    cfg_idx,
                )

                if fmbench_complete:
                    logger.info("Fmbench Run successful, Getting the folders now")
                    await asyncio.get_event_loop().run_in_executor(
                        self.executor,
                        check_and_retrieve_results_folder,
                        instance,
                        results_folder,
                    )
            if globals.config_data["run_steps"]["delete_ec2_instance"]:
                delete_ec2_instance(instance["instance_id"], instance["region"])
                self.instance_id_list.remove(instance["instance_id"])

    async def multi_deploy_fmbench(self, instance_details, remote_script_path):
        tasks = []

        # Create a task for each instance
        for instance in instance_details:
            # Make this async as well?
            # Format the script with the specific config file
            logger.info(f"Instance Details are: {instance}")
            # Create an async task for this instance
            tasks.append(
                self.execute_fmbench(
                    instance, instance["post_startup_script"], remote_script_path
                )
            )

        # Run all tasks concurrently
        await asyncio.gather(*tasks)

    async def run(self, instance_details, remote_script_path):
        """
        Main entry point to run the benchmarking process.
        
        Args:
            instance_details (List[Dict]): List of instance configurations
            remote_script_path (str): Path where the script will be uploaded on remote instances
        """
        self.instance_id_list = [instance["instance_id"] for instance in instance_details]
        await self.multi_deploy_fmbench(instance_details, remote_script_path)