import os
import sys
import json
import logging
import asyncio
import argparse
from fmbench_orchestrator.utils import *
from fmbench_orchestrator.utils.constants import *
from fmbench_orchestrator.cli import parse_args
from fmbench_orchestrator.utils.logger import logger
from fmbench_orchestrator.schema.handler import ConfigHandler
from fmbench_orchestrator.schema.instance_handler import InstanceHandler
from fmbench_orchestrator.core import BenchmarkRunner

from typing import List
from fmbench_orchestrator.schema.models import InstanceDetails, Config

async def deploy_benchmarking(instance_details: List[InstanceDetails], config: Config):
    """
    Deploy and run benchmarks on the specified instances.
    
    Args:
        instance_details: List of instance details with benchmark configurations
        config: Global configuration for the benchmark run
    """
    benchmark_runner = BenchmarkRunner()
    await benchmark_runner.run(instance_details, config)

def main():
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

    for instance in config_handler.instances:
        logger.info(f"Instance list is as follows: {instance.model_dump(mode='json')}")

    # Initialize and use the InstanceHandler
    instance_handler = InstanceHandler(config_handler=config_handler)
    instance_handler.deploy_instances(args)
    instance_handler.wait_for_instances()

    # Runs fmbench on the instances in parallel using typed Pydantic models
    asyncio.run(
        deploy_benchmarking(
            list(instance_handler.instance_details_map.values()),
            config_handler.config
        )
    )
    logger.info("all done")

if __name__ == "__main__":
    main()
