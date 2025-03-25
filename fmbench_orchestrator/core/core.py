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

from pydantic import BaseModel, Field, ConfigDict
from typing import List, Dict, Optional
import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

class BenchmarkParameters(BaseModel):
    """Parameters for benchmark script execution"""
    model_config = ConfigDict(frozen=True)

    local_mode: str = Field(default="no", pattern="^(yes|no)$")
    write_bucket: str = Field(...)
    additional_args: str = ""

class BenchmarkTask(BaseModel):
    """Single benchmark task configuration"""
    model_config = ConfigDict(frozen=True)

    instance_id: str = Field(pattern=r"^i-[a-f0-9]+$")
    instance_name: str
    config_file: str
    script_path: Path
    params: BenchmarkParameters

class BenchmarkRunner:
    """Manages concurrent benchmark execution across multiple instances"""
    
    def __init__(self):
        self.executor = ThreadPoolExecutor()
        self.instance_id_list: List[str] = []

    async def _prepare_parameters(self, instance: Dict) -> BenchmarkParameters:
        """Prepare and validate benchmark parameters"""
        try:
            pssp = instance.get("post_startup_script_params", {})
            params = BenchmarkParameters(
                local_mode="yes" if pssp.get("local_mode", False) else "no",
                write_bucket=pssp.get("write_bucket", POST_STARTUP_WRITE_BUCKET_VAR),
                additional_args=pssp.get("additional_args", "")
            )
            logger.info(
                "Prepared benchmark parameters",
                extra={
                    'instance_id': instance["instance_id"],
                    'instance_name': instance["instance_name"],
                    'params': params.model_dump()
                }
            )
            return params
        except ValidationError as e:
            logger.error(
                f"Invalid benchmark parameters: {e}",
                extra={'instance_id': instance["instance_id"]}
            )
            raise

    async def execute_fmbench(
        self,
        instance: Dict,
        post_install_script: str,
        remote_script_path: str
    ) -> None:
        """
        Execute benchmark on a single instance.
        
        Args:
            instance: Instance configuration
            post_install_script: Path to post-install script
            remote_script_path: Remote path for script deployment
        """
        log_context = {
            'instance_id': instance["instance_id"],
            'instance_name': instance["instance_name"]
        }
        
        logger.info("Starting instance benchmark", extra=log_context)

        # Check startup completion
        startup_complete = await asyncio.get_event_loop().run_in_executor(
            self.executor,
            wait_for_flag,
            instance,
            CONSTANTS.STARTUP_COMPLETE_FLAG_FPATH,
            CONSTANTS.CLOUD_INITLOG_PATH,
        )

        if not startup_complete:
            logger.error("Instance startup failed", extra=log_context)
            return

        try:
            # Upload additional files if specified
            if instance["upload_files"]:
                logger.info("Uploading additional files", extra=log_context)
                await upload_file_to_instance_async(
                    instance["hostname"],
                    instance["username"],
                    instance["key_file_path"],
                    file_paths=instance["upload_files"],
                )

            # Process each config file
            num_configs = len(instance["config_file"])
            for cfg_idx, config_file in enumerate(instance["config_file"], 1):
                try:
                    # Update context with current config
                    cfg_context = {
                        **log_context,
                        'config_index': cfg_idx,
                        'total_configs': num_configs
                    }

                    logger.info(
                        f"Processing config {cfg_idx}/{num_configs}",
                        extra=cfg_context
                    )

                    # Handle configuration file
                    remote_config_path = await handle_config_file_async(
                        instance,
                        config_file
                    )
                    
                    # Prepare benchmark parameters
                    params = await self._prepare_parameters(instance)
                # Format the script with the remote config file path
                # Change this later to be a better implementation, right now it is bad.

                    # Format and execute benchmark script
                    formatted_script = Path(post_install_script).read_text().format(
                        config_file=remote_config_path,
                        local_mode=params.local_mode,
                        write_bucket=params.write_bucket,
                        additional_args=params.additional_args,
                    )

                    logger.info("Executing benchmark script", extra=cfg_context)

                    # Execute script with retries
                    retries = 0
                    max_retries = 2
                    retry_sleep = 60
                    success = False

                    while retries <= max_retries:
                        try:
                            script_output = await asyncio.get_event_loop().run_in_executor(
                                self.executor,
                                upload_and_execute_script_invoke_shell,
                                instance["hostname"],
                                instance["username"],
                                instance["key_file_path"],
                                formatted_script,
                                remote_script_path,
                            )

                            if script_output:
                                success = True
                                logger.info(
                                    "Benchmark script execution started",
                                    extra={**cfg_context, 'output': script_output}
                                )
                                break
                            
                            logger.warning(
                                f"Empty script output on attempt {retries + 1}/{max_retries + 1}",
                                extra=cfg_context
                            )
                            
                        except Exception as e:
                            logger.error(
                                f"Script execution failed: {str(e)}",
                                extra=cfg_context,
                                exc_info=True
                            )
                        
                        if retries < max_retries:
                            logger.info(
                                f"Retrying in {retry_sleep}s",
                                extra=cfg_context
                            )
                            await asyncio.sleep(retry_sleep)
                        retries += 1

                    if not success:
                        logger.error(
                            "All execution attempts failed",
                            extra=cfg_context
                        )
                        continue

                    # Monitor benchmark completion
                    logger.info("Monitoring benchmark completion", extra=cfg_context)
                    fmbench_complete = await asyncio.get_event_loop().run_in_executor(
                        self.executor,
                        wait_for_flag,
                        instance,
                        CONSTANTS.FMBENCH_TEST_COMPLETE_FLAG_FPATH,
                        CONSTANTS.FMBENCH_LOG_PATH,
                        instance["fmbench_complete_timeout"],
                        CONSTANTS.SCRIPT_CHECK_INTERVAL_IN_SECONDS,
                    )

                    # Retrieve benchmark logs
                    logger.info("Retrieving benchmark logs", extra=cfg_context)
                    results_folder = os.path.join(
                        CONSTANTS.RESULTS_DIR,
                        globals.config_data["general"]["name"]
                    )

                    try:
                        # Retrieve logs (regardless of completion status)
                        await asyncio.get_event_loop().run_in_executor(
                            self.executor,
                            get_fmbench_log,
                            instance,
                            results_folder,
                            CONSTANTS.FMBENCH_LOG_REMOTE_PATH,
                            cfg_idx,
                        )

                        # Retrieve results if benchmark completed
                        if fmbench_complete:
                            logger.info(
                                "Benchmark completed successfully, retrieving results",
                                extra=cfg_context
                            )
                            await asyncio.get_event_loop().run_in_executor(
                                self.executor,
                                check_and_retrieve_results_folder,
                                instance,
                                results_folder,
                            )
                        else:
                            logger.warning(
                                "Benchmark did not complete within timeout",
                                extra=cfg_context
                            )

                    except Exception as e:
                        logger.error(
                            f"Failed to retrieve results: {str(e)}",
                            extra=cfg_context,
                            exc_info=True
                        )

                except Exception as e:
                    logger.error(
                        f"Benchmark execution failed: {str(e)}",
                        extra=cfg_context,
                        exc_info=True
                    )

        except Exception as e:
            logger.error(
                f"Instance benchmark failed: {str(e)}",
                extra=log_context,
                exc_info=True
            )
        finally:
            # Cleanup if needed
            if globals.config_data["run_steps"]["delete_ec2_instance"]:
                try:
                    logger.info("Cleaning up instance", extra=log_context)
                    delete_ec2_instance(instance["instance_id"], instance["region"])
                    self.instance_id_list.remove(instance["instance_id"])
                except Exception as e:
                    logger.error(
                        f"Failed to cleanup instance: {str(e)}",
                        extra=log_context,
                        exc_info=True
                    )

    async def multi_deploy_fmbench(self, instance_details, remote_script_path):
        tasks = {}
        results = {'succeeded': [], 'failed': []}

        # Create a task for each instance
        for instance in instance_details:
            instance_id = instance["instance_id"]
            instance_name = instance["instance_name"]
            
            logger.info(
                "Creating benchmark task",
                extra={
                    'instance_id': instance_id,
                    'instance_name': instance_name,
                    'operation': 'init'
                }
            )
            
            task = asyncio.create_task(
                self.execute_fmbench(
                    instance, instance["post_startup_script"], remote_script_path
                )
            )
            tasks[instance_id] = {
                'task': task,
                'instance_name': instance_name,
                'instance': instance
            }

        # Wait for all tasks to complete
        pending = list(tasks.values())
        while pending:
            done, pending = await asyncio.wait(
                [t['task'] for t in pending],
                return_when=asyncio.FIRST_COMPLETED
            )
            
            # Process completed tasks
            for completed_task in done:
                for instance_id, task_info in tasks.items():
                    if task_info['task'] == completed_task:
                        try:
                            await completed_task
                            results['succeeded'].append({
                                'instance_id': instance_id,
                                'instance_name': task_info['instance_name']
                            })
                            logger.info(
                                f"Benchmark completed successfully",
                                extra={
                                    'instance_id': instance_id,
                                    'instance_name': task_info['instance_name'],
                                    'operation': 'complete'
                                }
                            )
                        except Exception as e:
                            results['failed'].append({
                                'instance_id': instance_id,
                                'instance_name': task_info['instance_name'],
                                'error': str(e)
                            })
                            logger.error(
                                f"Benchmark failed: {str(e)}",
                                extra={
                                    'instance_id': instance_id,
                                    'instance_name': task_info['instance_name'],
                                    'operation': 'failed'
                                },
                                exc_info=True
                            )
                        break

        # Summary report
        logger.info(
            f"Benchmark run complete. "
            f"Succeeded: {len(results['succeeded'])}, "
            f"Failed: {len(results['failed'])}"
        )
        
        if results['failed']:
            failed_instances = [f"{i['instance_name']} ({i['error']})" for i in results['failed']]
            logger.error(f"Failed instances:\n" + "\n".join(failed_instances))

    async def run(self, instance_details, remote_script_path):
        """
        Main entry point to run the benchmarking process.
        
        Args:
            instance_details: List of instance configurations
            remote_script_path: Path where the script will be uploaded on remote instances
        """
        logger.info(
            f"Starting benchmark run with {len(instance_details)} instances",
            extra={'operation': 'benchmark_start'}
        )
        
        self.instance_id_list = [instance["instance_id"] for instance in instance_details]
        
        try:
            await self.multi_deploy_fmbench(instance_details, remote_script_path)
            logger.info(
                "Benchmark run completed successfully",
                extra={'operation': 'benchmark_complete'}
            )
        except Exception as e:
            logger.error(
                "Benchmark run failed",
                extra={
                    'operation': 'benchmark_failed',
                    'error': str(e)
                },
                exc_info=True
            )
            raise