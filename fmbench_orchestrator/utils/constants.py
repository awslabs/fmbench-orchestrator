from enum import Enum
from typing import List

# Infrastructure configuration paths
INFRA_YML_FPATH: str = "fmbench_orchestrator/configs/infra.yml"

# AWS Instance related constants
DEFAULT_DEVICE_NAME: str = "/dev/sda1"
EBS_IOPS: int = 16000
EBS_VOLUME_SIZE: int = 250
EBS_VOLUME_TYPE: str = "gp3"
MIN_INSTANCE_COUNT: int = 1
MAX_INSTANCE_COUNT: int = 1

# AWS Chips and AMI constants
AWS_CHIPS_PREFIX_LIST: List[str] = ["inf2", "trn1"]
IS_NEURON_INSTANCE = lambda instance_type: any(
    [instance_type.startswith(p) for p in AWS_CHIPS_PREFIX_LIST]
)

class AMIType(str, Enum):
    NEURON = "neuron"
    GPU = "gpu"
    CPU = "cpu"

# Flag and monitoring constants
STARTUP_COMPLETE_FLAG_FPATH: str = "/tmp/startup_complete.flag"
FMBENCH_TEST_COMPLETE_FLAG_FPATH: str = "/tmp/fmbench_completed.flag"
MAX_WAIT_TIME_FOR_STARTUP_SCRIPT_IN_SECONDS: int = 1500
SCRIPT_CHECK_INTERVAL_IN_SECONDS: int = 60
FMBENCH_LOG_PATH: str = "~/fmbench.log"
FMBENCH_LOG_REMOTE_PATH: str = "/home/{username}/fmbench.log"
CLOUD_INITLOG_PATH: str = "/var/log/cloud-init-output.log"

# Directory paths
RESULTS_DIR: str = "results"
DOWNLOAD_DIR_FOR_CFG_FILES: str = "downloaded_configs"

# FMBench specific constants
FMBENCH_CFG_PREFIX: str = "fmbench:"
FMBENCH_CFG_GH_PREFIX: str = (
    "https://raw.githubusercontent.com/aws-samples/foundation-model-benchmarking-tool/refs/heads/main/fmbench/configs/"
)
FMBENCH_GH_REPO: str = (
    "https://github.com/aws-samples/foundation-model-benchmarking-tool.git"
)
