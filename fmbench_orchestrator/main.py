import os
import sys
import json
import logging
import asyncio
import argparse
from fmbench_orchestrator.utils import *
from fmbench_orchestrator.utils.constants import CONSTANTS
import fmbench_orchestrator.globals as globals
from fmbench_orchestrator.cli import parse_args
from fmbench_orchestrator.utils.logger import logger
from fmbench_orchestrator.schema.handler import ConfigHandler
from fmbench_orchestrator.instance_handler import InstanceHandler
from fmbench_orchestrator.core import BenchmarkRunner

async def deploy_benchmarking(instance_details, remote_script_path):
    """
    Deploy and run benchmarks on the specified instances.
    """
    benchmark_runner = BenchmarkRunner()
    await benchmark_runner.run(instance_details, remote_script_path)

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
