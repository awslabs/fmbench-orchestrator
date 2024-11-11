from enum import Enum
from typing import Optional, List, Dict

# Define constants
FMBENCH_PACKAGE_NAME: str = "fmbench"
remote_script_path: str = "/home/{username}/run_fmbench.sh"
YAML_FILE_PATH: str = "config.yml"
DEFAULT_EC2_USERNAME: str = "ec2-user"
BYO_DATASET_FILE_PATH: str = "/tmp/fmbench-read/source_data/"
POST_STARTUP_LOCAL_MODE_VAR: str = "yes"
POST_STARTUP_WRITE_BUCKET_VAR: str = "placeholder"
AWS_CHIPS_PREFIX_LIST: List[str] = ["inf2", "trn1"]
IS_NEURON_INSTANCE = lambda instance_type: any([instance_type.startswith(p) for p in AWS_CHIPS_PREFIX_LIST])

class AMI_TYPE(str, Enum):
    NEURON = 'neuron'
    GPU = "gpu"

# Define a dictionary for common AMIs and their corresponding usernames
AMI_USERNAME_MAP: Dict = {
    "ami-": "ec2-user",  # Amazon Linux AMIs start with 'ami-'
    "ubuntu": "ubuntu",  # Ubuntu AMIs contain 'ubuntu' in their name
}

# Default constants for ec2 instance creation
DEFAULT_DEVICE_NAME: str = '/dev/sda/1'
EBS_IOPS: int = 16000
EBS_VOLUME_SIZE: int = 250
EBS_VOLUME_TYPE: str = "gp3"
CAPACITY_RESERVATION_PREFERENCE: str = "none"
MIN_INSTANCE_COUNT: int = 1
MAX_INSTANCE_COUNT: int = 1

# Default constants for DynamoDB creation
DEFAULT_TABLE_NAME = "fmbench-orchestrator"

# all region specific AMI mapping information for gpu/neuron based instances
# are given in this "ami_mapping.yml" file. This file currently contains information
# on us-east-1, us-east-2, us-west-1, us-west-2 for gpu and neuron instances. To add
# or change the ami mapping for other regions, modify this file. This model benchmarking
# configuration file will utilize the region (determined by the region metadata) or if the
# user provides it in the model config to get the AMI mapping and launch the specific
# instance accordingly.
AMI_MAPPING_FNAME: str = 'ami_mapping.yml'

# FMBench results file path
FMBENCH_RESULTS_FOLDER_PATTERN: str = "$HOME/results-*"

# flag related variables
STARTUP_COMPLETE_FLAG_FPATH: str = "/tmp/startup_complete.flag"
FMBENCH_TEST_COMPLETE_FLAG_FPATH: str = "/tmp/fmbench_completed.flag"
MAX_WAIT_TIME_FOR_STARTUP_SCRIPT_IN_SECONDS: int = 1200
SCRIPT_CHECK_INTERVAL_IN_SECONDS: int = 60
FMBENCH_LOG_PATH: str = "~/fmbench.log"
FMBENCH_LOG_REMOTE_PATH: str = "/home/{username}/fmbench.log"
CLOUD_INITLOG_PATH: str = "/var/log/cloud-init-output.log"

# misc directory paths
RESULTS_DIR: str = "results"
DOWNLOAD_DIR_FOR_CFG_FILES: str = "downloaded_configs"

# if the config file path starts with this then we know
# we need to download it from fmbench github repo
FMBENCH_CFG_PREFIX: str = "fmbench:"
FMBENCH_CFG_GH_PREFIX: str = "https://raw.githubusercontent.com/aws-samples/foundation-model-benchmarking-tool/refs/heads/main/src/fmbench/configs/"

