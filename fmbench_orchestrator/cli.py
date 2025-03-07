"""Command-line interface for FMBench orchestrator."""

import argparse
import logging
from fmbench_orchestrator.utils.constants import *
from fmbench_orchestrator.utils.logger import logger


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Run FMBench orchestrator with a specified config file."
    )
    parser.add_argument(
        "--config-file",
        type=str,
        help="Path to your Config File",
        required=False,
        default="fmbench_orchestrator/configs/ec2.yml",
    )
    parser.add_argument(
        "--ami-mapping-file",
        type=str,
        help="Path to a config file containing the region->instance type->AMI mapping",
        required=False,
        default="fmbench_orchestrator/configs/ami_mapping.yml",
    )
    parser.add_argument(
        "--fmbench-config-file",
        type=str,
        help='Config file to use with fmbench, this is used if the orchestrator config file uses the "{{config_file}}" format for specifying the fmbench config file',
        required=False,
    )
    parser.add_argument(
        "--infra-config-file",
        type=str,
        help="Path to the infrastructure config file",
        default=INFRA_YML_FPATH,
    )
    parser.add_argument(
        "--write-bucket",
        type=str,
        help="S3 bucket to store model files for benchmarking on SageMaker",
        required=False,
    )
    parser.add_argument(
        "--fmbench-latest",
        type=bool,
        help="argument to check if the user wants to make a new build of the fmbench package and then use the orchestrator.",
        required=False,
    )
    parser.add_argument(
        "--fmbench-repo",
        type=str,
        help="GitHub repo for FMBench, if set then then this repo is used for installing FMBench rather than doing an FMBench install from PyPI. Default is None i.e. use FMBench package from PyPi",
        required=False,
    )

    args = parser.parse_args()
    logger.info(f"CLI Arguments: {args}")
    return args
