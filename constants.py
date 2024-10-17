from enum import Enum
from typing import Optional, List, Dict

# Define constants
remote_script_path: str = "/home/ubuntu/run_fmbench.sh"
YAML_FILE_PATH: str = "config.yml"
DEFAULT_EC2_USERNAME: str = "ec2-user"
BYO_DATASET_FILE_PATH: str = "/tmp/fmbench-read/source_data/"
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
AMI_MAPPING_PARAM_NAME: str = 'ami_mapping'

# FMBench results file path
FMBENCH_RESULTS_FOLDER_PATTERN: str = "$HOME/results-*"

# flag related variables
STARTUP_COMPLETE_FLAG_FPATH: str = "/tmp/startup_complete.flag"
FMBENCH_TEST_COMPLETE_FLAG_FPATH: str = "/tmp/fmbench_completed.flag"
MAX_WAIT_TIME_FOR_STARTUP_SCRIPT_IN_SECONDS: int = 1200
SCRIPT_CHECK_INTERVAL_IN_SECONDS: int = 60
FMBENCH_LOG_PATH: str = "~/fmbench.log"
CLOUD_INITLOG_PATH: str = "/var/log/cloud-init-output.log"

# misc directory paths
RESULTS_DIR: str = "results"
DOWNLOAD_DIR_FOR_CFG_FILES: str = "downloaded_configs"

AMI_NAME_MAP = {
    "gpu": "Deep Learning OSS Nvidia Driver AMI GPU PyTorch 2.4 (Ubuntu 22.04)",
    "neuron": "Deep Learning AMI Neuron (Ubuntu 22.04)",
    "cpu": "Amazon Linux 2 AMI (HVM) - Kernel 5.10, SSD Volume Type",
}

