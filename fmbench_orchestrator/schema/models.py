from enum import Enum
from typing import List, Optional, Dict, Union, Annotated
from pydantic import BaseModel, Field, ValidationError, ConfigDict, BeforeValidator, model_validator
from pydantic.functional_validators import field_validator
from pathlib import Path
from typing_extensions import TypedDict

class ConfigVersion(str, Enum):
    """Configuration schema version"""
    V1_0 = "1.0"
    V1_1 = "1.1"

class InstanceType(str, Enum):
    """Valid EC2 instance types"""
    GPU = "gpu"
    CPU = "cpu"
    NEURON = "neuron"

class VolumeType(str, Enum):
    """Valid EBS volume types"""
    GP3 = "gp3"
    GP2 = "gp2"
    IO2 = "io2"


class UploadFile(BaseModel):
    """File upload configuration"""
    model_config = ConfigDict(frozen=True)

    local: Annotated[Path, BeforeValidator(lambda x: Path(str(x)))]
    remote: Annotated[Path, BeforeValidator(lambda x: Path(str(x)))]

    @field_validator('local')
    def validate_local_path(cls, v: Path) -> Path:
        """Ensure local file exists"""
        if not v.exists():
            raise ValueError(f"Local file {v} does not exist")
        return v


class EC2Settings(BaseModel):
    """Base EC2 settings that can be reused across instances"""
    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    schema_version: ConfigVersion = Field(
        default=ConfigVersion.V1_1,
        description="Configuration schema version"
    )
    
    region: Annotated[
        Optional[str],
        Field(pattern=r"^[a-z]{2}-[a-z]+-\d{1}$", description="AWS region (e.g. us-west-2)")
    ] = None

    ami_id: Annotated[
        Union[str, Dict[InstanceType, Optional[str]]],
        Field(description="AMI ID or type mapping")
    ]

    device_name: str = "/dev/sda1"
    ebs_del_on_termination: bool = True
    ebs_Iops: Literal[16000] = 16000  # Fixed IOPS value
    ebs_VolumeSize: Annotated[int, Field(ge=8, le=16384)] = 250
    ebs_VolumeType: VolumeType = VolumeType.GP3

    startup_script: Annotated[
        Path,
        BeforeValidator(lambda x: Path(str(x)))
    ] = Path("startup_scripts/ubuntu_startup.txt")

    post_startup_script: Annotated[
        Path,
        BeforeValidator(lambda x: Path(str(x)))
    ] = Path("post_startup_scripts/fmbench.txt")

    fmbench_complete_timeout: Annotated[int, Field(ge=60, le=86400)] = 2400

    @field_validator("ami_id")
    def validate_ami_id(cls, v: Union[str, Dict[InstanceType, Optional[str]]]) -> Union[str, Dict[InstanceType, Optional[str]]]:
        """Validate AMI ID format"""
        if isinstance(v, str):
            if not v.startswith("ami-"):
                raise ValueError("AMI ID must start with 'ami-'")
            return v
        elif isinstance(v, dict):
            if len(v) != 1:
                raise ValueError("AMI mapping must have exactly one key")
            if not all(isinstance(k, InstanceType) for k in v.keys()):
                raise ValueError("AMI mapping keys must be valid instance types")
            return v
        raise ValueError("ami_id must be either a string AMI ID or a mapping dict")

    @model_validator(mode='after')
    def validate_paths(self) -> 'EC2Settings':
        """Validate that all paths exist"""
        for script in [self.startup_script, self.post_startup_script]:
            if not script.exists():
                raise ValueError(f"Script file not found: {script}")
        return self


from typing import Literal

class InstanceConfig(EC2Settings):
    """Configuration for an individual EC2 instance"""
    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    instance_type: Annotated[str, Field(pattern=r"^[a-z0-9]+\.[a-z0-9]+$")]
    fmbench_config: Annotated[List[Path], Field(min_length=1)]
    deploy: bool = True
    post_startup_script_params: Optional[Dict[str, Union[str, bool, int]]] = None
    upload_files: Optional[List[UploadFile]] = None
    instance_id: Optional[Annotated[str, Field(pattern=r"^i-[a-f0-9]+$")]] = None
    CapacityReservationId: Optional[Annotated[str, Field(pattern=r"^cr-[a-f0-9]+$")]] = None
    CapacityReservationPreference: Literal["none", "open"] = "none"
    CapacityReservationResourceGroupArn: Optional[str] = None

    @field_validator("fmbench_config")
    def validate_fmbench_config(cls, v: List[Path]) -> List[Path]:
        """Validate fmbench config paths exist"""
        if not v:
            raise ValueError("fmbench_config cannot be empty")
            
        validated_paths: List[Path] = []
        for path in v:
            if path is None or str(path) == "None":
                raise ValueError("fmbench_config paths cannot be None")
            path_obj = Path(str(path))
            if not path_obj.exists():
                raise ValueError(f"Config file not found: {path_obj}")
            validated_paths.append(path_obj)
            
        return validated_paths

    @field_validator("upload_files", mode="before")
    def validate_upload_files(cls, v: Optional[List[Union[Dict, UploadFile]]]) -> Optional[List[UploadFile]]:
        """Convert dict-style upload files to UploadFile objects"""
        if v is None:
            return None
        if not isinstance(v, list):
            raise ValueError("upload_files must be a list")
        return [UploadFile(**item) if isinstance(item, dict) else item for item in v]

    @model_validator(mode='after')
    def validate_startup_params(self) -> 'InstanceConfig':
        """Validate post startup script parameters"""
        if self.post_startup_script_params:
            allowed_keys = {"local_mode", "write_bucket", "additional_args"}
            invalid_keys = set(self.post_startup_script_params.keys()) - allowed_keys
            if invalid_keys:
                raise ValueError(f"Invalid post startup script parameters: {invalid_keys}")
        return self


class SecurityGroupConfig(BaseModel):
    """Security group configuration"""
    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    group_name: Annotated[str, Field(min_length=1)] = "fmbench_orchestrator_sg"
    description: Annotated[str, Field(min_length=1)] = "MultiDeploy EC2 Security Group"
    vpc_id: Optional[Annotated[str, Field(pattern=r"^vpc-[a-f0-9]+$")]] = None


class KeyPairConfig(BaseModel):
    """Key pair configuration"""
    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    key_pair_name: Annotated[str, Field(min_length=1)] = "fmbench_orchestrator_key_pair"


class RunStepsConfig(BaseModel):
    """Steps to execute during orchestration"""
    model_config = ConfigDict(frozen=True)

    security_group_creation: bool = True
    key_pair_generation: bool = True
    deploy_ec2_instance: bool = True
    delete_ec2_instance: bool = True


class AWSConfig(BaseModel):
    """AWS-specific configuration"""
    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    hf_token_fpath: Annotated[Path, BeforeValidator(lambda x: Path(str(x)))]
    region: Optional[Annotated[str, Field(pattern=r"^[a-z]{2}-[a-z]+-\d{1}$")]] = None

    @field_validator("hf_token_fpath")
    def validate_hf_token(cls, v: Path) -> Path:
        if not v.is_file():
            raise ValueError(f"HuggingFace token file not found at {v}")
        token = v.read_text().strip()
        if len(token) <= 4:
            raise ValueError("HuggingFace token is too small or invalid")
        return v


class GeneralConfig(BaseModel):
    """General configuration settings"""
    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    name: Annotated[str, Field(min_length=1)]


class MainConfig(BaseModel):
    """Root configuration model"""
    model_config = ConfigDict(
        frozen=True,
        validate_assignment=True,
        extra="forbid",
        str_strip_whitespace=True
    )

    general: GeneralConfig
    defaults: Optional[EC2Settings]
    instances: Annotated[List[InstanceConfig], Field(min_length=1)]
    aws: AWSConfig
    run_steps: RunStepsConfig
    security_group: SecurityGroupConfig
    key_pair_gen: KeyPairConfig

    @model_validator(mode='after')
    def validate_and_apply_defaults(self) -> 'MainConfig':
        """Validate configuration and apply defaults where needed"""
        for instance in self.instances:
            # Apply region defaults
            if instance.region is None:
                if self.defaults and self.defaults.region:
                    instance.region = self.defaults.region
                elif self.aws.region:
                    instance.region = self.aws.region

            # Apply other defaults if they exist and values are None
            if self.defaults:
                for field_name, field in self.defaults.model_fields.items():
                    if field_name != "region":  # Skip region as we handled it above
                        instance_value = getattr(instance, field_name, None)
                        if instance_value is None:
                            default_value = getattr(self.defaults, field_name)
                            setattr(instance, field_name, default_value)
        return self


class InstanceDetails(BaseModel):
    """Model for tracking instance details during deployment"""
    model_config = ConfigDict(
        frozen=True,
        validate_assignment=True,
        extra="forbid",
        populate_by_name=True,  # Allows both PRIVATE_KEY_FNAME and key_file_path
        str_strip_whitespace=True
    )

    instance_id: Annotated[str, Field(pattern=r"^i-[a-f0-9]+$")]
    fmbench_config: Annotated[List[Path], Field(min_length=1)]
    post_startup_script: Annotated[Path, BeforeValidator(lambda x: Path(str(x)))]
    post_startup_script_params: Optional[Dict[str, Union[str, bool, int]]] = None
    fmbench_complete_timeout: Annotated[int, Field(ge=60, le=86400)]
    region: Annotated[str, Field(pattern=r"^[a-z]{2}-[a-z]+-\d{1}$")]
    key_file_path: Annotated[str, Field(alias="PRIVATE_KEY_FNAME")]
    upload_files: Optional[List[UploadFile]] = None
    hostname: Optional[str] = None
    username: Annotated[str, Field(min_length=1)] = "ubuntu"
    instance_name: Optional[str] = None

    @model_validator(mode='after')
    def validate_paths(self) -> 'InstanceDetails':
        """Validate that paths exist"""
        if not Path(self.post_startup_script).exists():
            raise ValueError(f"Post startup script not found: {self.post_startup_script}")
        
        if not Path(self.key_file_path).exists():
            raise ValueError(f"Key file not found: {self.key_file_path}")

        for config_path in self.fmbench_config:
            if not config_path.exists():
                raise ValueError(f"Config file not found: {config_path}")
            
        return self
