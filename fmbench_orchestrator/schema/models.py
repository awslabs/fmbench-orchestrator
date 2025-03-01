from typing import List, Optional, Dict, Union
from pydantic import BaseModel, Field, field_validator, ValidationInfo
from pathlib import Path


class UploadFile(BaseModel):
    """File upload configuration"""

    local: str
    remote: str


class EC2Settings(BaseModel):
    """Base EC2 settings that can be reused across instances"""

    region: Optional[str] = None  # Can be None to use default from aws config
    ami_id: Union[
        str, Dict[str, Optional[str]]
    ]  # Can be direct AMI ID or mapping like {"gpu": None}
    device_name: str = "/dev/sda1"
    ebs_del_on_termination: bool = True
    ebs_Iops: int = 16000
    ebs_VolumeSize: int = 250
    ebs_VolumeType: str = "gp3"
    startup_script: str = "startup_scripts/ubuntu_startup.txt"
    post_startup_script: str = "post_startup_scripts/fmbench.txt"
    fmbench_complete_timeout: int = 2400

    @field_validator("ami_id")
    @classmethod
    def validate_ami_id(cls, v):
        """Validate AMI ID format"""
        if isinstance(v, str):
            # Direct AMI ID (e.g., "ami-123456")
            return v
        elif isinstance(v, dict):
            # AMI type mapping (e.g., {"gpu": None} or {"gpu": "ami-123456"})
            if len(v) != 1:
                raise ValueError(
                    "AMI mapping must have exactly one key (gpu, cpu, or neuron)"
                )
            key = next(iter(v))
            if key not in ["gpu", "cpu", "neuron"]:
                raise ValueError(
                    f"Invalid AMI type: {key}. Must be one of: gpu, cpu, neuron"
                )
            return v
        raise ValueError("ami_id must be either a string AMI ID or a mapping dict")


class InstanceConfig(EC2Settings):
    """Configuration for an individual EC2 instance"""

    instance_type: str
    fmbench_config: List[str]
    deploy: bool = True
    post_startup_script_params: Optional[Dict] = None
    upload_files: Optional[List[UploadFile]] = None
    instance_id: Optional[str] = None
    CapacityReservationId: Optional[str] = None
    CapacityReservationPreference: str = "none"
    CapacityReservationResourceGroupArn: Optional[str] = None

    @field_validator("upload_files", mode="before")
    @classmethod
    def validate_upload_files(cls, v):
        """Convert dict-style upload files to UploadFile objects"""
        if v is None:
            return None
        if isinstance(v, list):
            return [
                UploadFile(**item) if isinstance(item, dict) else item for item in v
            ]
        return v

    @field_validator("fmbench_config")
    @classmethod
    def validate_fmbench_config(cls, v):
        """Validate fmbench config paths"""
        if not v:
            raise ValueError("fmbench_config cannot be empty")
        for path in v:
            if path is None or path == "None":
                raise ValueError("fmbench_config paths cannot be None")
        return v


class SecurityGroupConfig(BaseModel):
    """Security group configuration"""

    group_name: str = "fmbench_orchestrator_sg"
    description: str = "MultiDeploy EC2 Security Group"
    vpc_id: Optional[str] = None


class KeyPairConfig(BaseModel):
    """Key pair configuration"""

    key_pair_name: str = "fmbench_orchestrator_key_pair"


class RunStepsConfig(BaseModel):
    """Steps to execute during orchestration"""

    security_group_creation: bool = True
    key_pair_generation: bool = True
    deploy_ec2_instance: bool = True
    delete_ec2_instance: bool = True


class AWSConfig(BaseModel):
    """AWS-specific configuration"""

    hf_token_fpath: Path
    region: Optional[str] = None  # Default region if not specified in instance

    @field_validator("hf_token_fpath")
    @classmethod
    def validate_hf_token(cls, v):
        if not v.is_file():
            raise ValueError(f"HuggingFace token file not found at {v}")
        token = v.read_text().strip()
        if len(token) <= 4:
            raise ValueError("HuggingFace token is too small or invalid")
        return v


class GeneralConfig(BaseModel):
    """General configuration settings"""

    name: str


class MainConfig(BaseModel):
    """Root configuration model"""

    general: GeneralConfig
    defaults: Optional[EC2Settings]
    instances: List[InstanceConfig]
    aws: AWSConfig
    run_steps: RunStepsConfig
    security_group: SecurityGroupConfig
    key_pair_gen: KeyPairConfig

    @field_validator("instances")
    @classmethod
    def validate_instances(cls, v, info: ValidationInfo):
        """Validate instances and apply defaults where needed"""
        data = info.data
        defaults = data.get("defaults")
        aws_config = data.get("aws")

        for instance in v:
            # If instance has no region, try defaults, then aws_config
            if instance.region is None and defaults:
                instance.region = defaults.region
            if instance.region is None and aws_config:
                instance.region = aws_config.region

            # Apply other defaults if they exist
            if defaults:
                for field, value in defaults.dict().items():
                    if field != "region":  # Skip region as we handled it above
                        if getattr(instance, field) is None:
                            setattr(instance, field, value)
        return v

    class Config:
        """Pydantic config"""

        validate_assignment = True
        extra = "forbid"
