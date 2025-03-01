from typing import List, Optional, Dict
from pydantic import BaseModel, Field
from src.utils.constants import (
    DEFAULT_DEVICE_NAME,
    EBS_IOPS,
    EBS_VOLUME_SIZE,
    EBS_VOLUME_TYPE,
)


class EC2Settings(BaseModel):
    """Base EC2 settings that can be reused across instances"""

    region: str
    ami_id: str
    device_name: str = DEFAULT_DEVICE_NAME
    ebs_del_on_termination: bool = True
    ebs_Iops: int = EBS_IOPS
    ebs_VolumeSize: int = EBS_VOLUME_SIZE
    ebs_VolumeType: str = EBS_VOLUME_TYPE
    startup_script: str
    post_startup_script: str
    fmbench_complete_timeout: int = 2400


class InstanceConfig(EC2Settings):
    """Configuration for an EC2 instance"""

    instance_type: str
    deploy: bool = True
    fmbench_config: List[str]
    post_startup_script_params: Optional[Dict] = None
    upload_files: Optional[List[str]] = None


class SecurityGroupConfig(BaseModel):
    """Security group configuration"""

    group_name: str = Field(..., description="Name of the security group")
    description: str = Field(..., description="Description of the security group")
    vpc_id: Optional[str] = Field(None, description="VPC ID for the security group")


class KeyPairConfig(BaseModel):
    """Key pair configuration"""

    key_pair_name: str = Field(..., description="Name of the key pair")


class RunStepsConfig(BaseModel):
    """Configuration for which steps to run"""

    security_group_creation: bool = True
    key_pair_generation: bool = True
    deploy_ec2_instance: bool = True
    delete_ec2_instance: bool = True


class AWSConfig(BaseModel):
    """AWS-specific configuration"""

    hf_token_fpath: str = Field(..., description="Path to Hugging Face token file")
    region: str = Field(..., description="AWS region")
    iam_instance_profile_arn: Optional[str] = None


class GeneralConfig(BaseModel):
    """General configuration"""

    name: str = Field(..., description="Name of the configuration")


class MainConfig(BaseModel):
    """Main configuration model"""

    general: GeneralConfig
    aws: AWSConfig
    run_steps: RunStepsConfig
    security_group: SecurityGroupConfig
    key_pair_gen: KeyPairConfig
    defaults: EC2Settings
    instances: List[InstanceConfig]
