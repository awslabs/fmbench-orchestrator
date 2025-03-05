from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
from pydantic import BaseModel, Field, field_validator
from fmbench_orchestrator.utils.yaml_utils import load_yaml_file
from fmbench_orchestrator.utils.logger import logger
from .models import MainConfig
import json
import time
from botocore.exceptions import NoCredentialsError


class ConfigHandlerSettings(BaseModel):
    """Settings for the ConfigHandler"""

    config_file: Path = Field(..., description="Main configuration file path")
    ami_mapping_file: Optional[Path] = Field(
        None, description="AMI mapping configuration file path"
    )
    fmbench_config_file: Optional[Path] = Field(
        None, description="FMBench configuration file path"
    )
    infra_config_file: Optional[Path] = Field(
        None, description="Infrastructure configuration file path"
    )
    write_bucket: Optional[str] = Field(
        None, description="S3 bucket for writing results"
    )

    @field_validator(
        "config_file", "ami_mapping_file", "fmbench_config_file", "infra_config_file"
    )
    @classmethod
    def validate_file_exists(cls, v: Optional[Path]) -> Optional[Path]:
        if v is not None and not v.exists():
            raise ValueError(f"File at {v} does not exist")
        return v


class ConfigHandler(BaseModel):
    """Handler for loading and managing configuration"""

    settings: ConfigHandlerSettings
    config: Optional[MainConfig] = None
    raw_config: Optional[Dict[str, Any]] = None
    hf_token: Optional[str] = None

    class Config:
        arbitrary_types_allowed = True

    @classmethod
    def from_args(
        cls,
        config_file: str,
        ami_mapping_file: Optional[str] = None,
        fmbench_config_file: Optional[str] = None,
        infra_config_file: Optional[str] = None,
        write_bucket: Optional[str] = None,
    ) -> "ConfigHandler":
        """Create ConfigHandler from argument strings"""
        settings = ConfigHandlerSettings(
            config_file=Path(config_file),
            ami_mapping_file=Path(ami_mapping_file) if ami_mapping_file else None,
            fmbench_config_file=(
                Path(fmbench_config_file) if fmbench_config_file else None
            ),
            infra_config_file=Path(infra_config_file) if infra_config_file else None,
            write_bucket=write_bucket,
        )
        return cls(settings=settings)

    def load_config(self) -> "ConfigHandler":
        """Load and validate configuration"""
        logger.info("Loading configuration files...")

        # Use load_yaml_file to handle AMI mapping and configuration merging
        self.raw_config = load_yaml_file(
            str(self.settings.config_file),
            (
                str(self.settings.ami_mapping_file)
                if self.settings.ami_mapping_file
                else None
            ),
            (
                str(self.settings.fmbench_config_file)
                if self.settings.fmbench_config_file
                else None
            ),
            (
                str(self.settings.infra_config_file)
                if self.settings.infra_config_file
                else None
            ),
            self.settings.write_bucket,
        )

        logger.info(f"Loaded raw config: {self.raw_config}")

        try:
            # Create MainConfig from the processed configuration
            self.config = MainConfig(**self.raw_config)
            logger.info("Successfully validated configuration")
        except Exception as e:
            logger.error(f"Failed to validate configuration: {e}")
            raise

        # Load HF token after config validation
        self._load_hf_token()
        return self

    def get_hf_token(self) -> str:
        """Get the loaded HuggingFace token"""
        if not self.hf_token:
            self._load_hf_token()
        return self.hf_token

    def _load_hf_token(self) -> None:
        """Load and validate HuggingFace token"""
        if not self.config:
            raise ValueError("Config not loaded. Call load_config() first")

        token_path = self.config.aws.hf_token_fpath
        logger.info(f"Loading HuggingFace token from {token_path}")

        try:
            self.hf_token = token_path.read_text().strip()
            if len(self.hf_token) <= 4:
                raise ValueError("HuggingFace token is too short or invalid")
            logger.info("Successfully loaded HuggingFace token")
        except Exception as e:
            logger.error(f"Failed to load HuggingFace token: {e}")
            raise

    @property
    def instances(self) -> list:
        """Get instance configurations"""
        self._ensure_config_loaded()
        return self.config.instances

    @property
    def aws_config(self):
        """Get AWS configuration"""
        self._ensure_config_loaded()
        return self.config.aws

    @property
    def run_steps(self):
        """Get run steps configuration"""
        self._ensure_config_loaded()
        return self.config.run_steps

    @property
    def security_group(self):
        """Get security group configuration"""
        self._ensure_config_loaded()
        return self.config.security_group

    @property
    def key_pair(self):
        """Get key pair configuration"""
        self._ensure_config_loaded()
        return self.config.key_pair_gen

    @property
    def defaults(self):
        """Get default EC2 settings"""
        self._ensure_config_loaded()
        return self.config.defaults

    def _ensure_config_loaded(self):
        """Ensure configuration is loaded before accessing properties"""
        if not self.config:
            raise ValueError("Configuration not loaded. Call load_config() first")


class InstanceHandler:
    """Handler for managing EC2 instances"""

    def __init__(self, config_handler: ConfigHandler):
        self.config_handler = config_handler
        self.instance_id_list: List[str] = []
        self.instance_data_map: Dict[str, Dict] = {}

    def deploy_instances(self, args) -> Tuple[List[str], Dict[str, Dict]]:
        """Deploy EC2 instances based on configuration"""
        logger.info("Deploying EC2 Instances")
        if not self.config_handler.run_steps.deploy_ec2_instance:
            return self.instance_id_list, self.instance_data_map

        try:
            iam_arn = get_iam_role()
        except Exception as e:
            logger.error(f"Cannot get IAM Role due to exception {e}")
            raise

        if not iam_arn:
            raise NoCredentialsError(
                "Unable to locate credentials. Please check if an IAM role is attached to your instance."
            )

        logger.info(f"iam arn: {iam_arn}")
        num_instances: int = len(self.config_handler.instances)

        for idx, instance in enumerate(self.config_handler.instances, 1):
            logger.info(
                f"going to create instance {idx} of {num_instances}, instance={instance.model_dump(mode='json')}"
            )

            if not instance.deploy:
                logger.warning(
                    f"deploy=False for instance={json.dumps(instance.model_dump(mode='json'), indent=2)}, skipping it..."
                )
                continue

            self._deploy_single_instance(instance, idx, iam_arn, args)

        return self.instance_id_list, self.instance_data_map

    def _deploy_single_instance(self, instance, idx: int, iam_arn: str, args):
        """Deploy a single EC2 instance"""
        region = instance.region or self.config_handler.aws_config.region
        startup_script = instance.startup_script
        logger.info(f"Region Set for instance is: {region}")

        if self.config_handler.run_steps.security_group_creation:
            logger.info("Creating Security Groups. getting them by name if they exist")
            sg_id = get_sg_id(region)

        if region is None:
            raise ValueError("Region is not provided in the configuration file.")

        PRIVATE_KEY_FNAME, PRIVATE_KEY_NAME = get_key_pair(region)

        user_data_script = self._prepare_user_data_script(
            startup_script, self.config_handler.get_hf_token(), args
        )

        if instance.instance_id is None:
            self._create_new_instance(
                instance,
                idx,
                PRIVATE_KEY_NAME,
                sg_id,
                user_data_script,
                iam_arn,
                region,
                PRIVATE_KEY_FNAME,
            )
        else:
            self._handle_existing_instance(
                instance, user_data_script, region, startup_script, PRIVATE_KEY_FNAME
            )

    def _prepare_user_data_script(
        self, startup_script: str, hf_token: str, args
    ) -> str:
        """Prepare the user data script with necessary replacements"""
        with open(startup_script, "r") as file:
            user_data_script = file.read()

        user_data_script = user_data_script.replace("__HF_TOKEN__", hf_token)
        user_data_script = user_data_script.replace("__neuron__", "True")

        if args.fmbench_latest is True and args.fmbench_repo is None:
            args.fmbench_repo = FMBENCH_GH_REPO
            logger.info(
                f"FMBench latest is set to {args.fmbench_latest}, fmbench_repo is now set to {args.fmbench_repo}"
            )
        elif args.fmbench_repo is not None:
            args.fmbench_latest = True
            logger.info(
                f"FMBench latest is now set to {args.fmbench_latest}, fmbench_repo is set to {args.fmbench_repo}"
            )

        user_data_script = user_data_script.replace(
            "__fmbench_latest__", str(args.fmbench_latest)
        )
        user_data_script = user_data_script.replace(
            "__fmbench_repo__", str(args.fmbench_repo)
        )
        logger.info(f"User data script: {user_data_script}")
        return user_data_script

    def _create_new_instance(
        self,
        instance,
        idx: int,
        key_name: str,
        sg_id: str,
        user_data_script: str,
        iam_arn: str,
        region: str,
        private_key_fname: str,
    ):
        """Create a new EC2 instance"""
        instance_id = create_ec2_instance(
            idx,
            key_name,
            sg_id,
            user_data_script,
            instance.ami_id,
            instance.instance_type,
            iam_arn,
            region,
            instance.device_name,
            instance.ebs_del_on_termination,
            instance.ebs_Iops,
            instance.ebs_VolumeSize,
            instance.ebs_VolumeType,
            instance.CapacityReservationPreference,
            instance.CapacityReservationId,
            instance.CapacityReservationResourceGroupArn,
        )
        self._add_instance_to_maps(instance, instance_id, region, private_key_fname)

    def _handle_existing_instance(
        self,
        instance,
        user_data_script: str,
        region: str,
        startup_script: str,
        private_key_fname: str,
    ):
        """Handle an existing EC2 instance"""
        if not private_key_fname:
            logger.error(
                "Private key not found, not adding instance to instance id list"
            )
            return

        if upload_and_run_script(
            instance.instance_id,
            private_key_fname,
            user_data_script,
            region,
            startup_script,
        ):
            logger.info(
                f"Startup script uploaded and executed on instance {instance.instance_id}"
            )
            self._add_instance_to_maps(
                instance, instance.instance_id, region, private_key_fname
            )
        else:
            logger.error(
                f"Failed to upload and execute startup script on instance {instance.instance_id}"
            )

    def _add_instance_to_maps(
        self, instance, instance_id: str, region: str, private_key_fname: str
    ):
        """Add instance details to tracking maps"""
        self.instance_id_list.append(instance_id)
        self.instance_data_map[instance_id] = {
            "fmbench_config": instance.fmbench_config,
            "post_startup_script": instance.post_startup_script,
            "post_startup_script_params": instance.post_startup_script_params,
            "fmbench_complete_timeout": instance.fmbench_complete_timeout,
            "region": region,
            "PRIVATE_KEY_FNAME": private_key_fname,
            "upload_files": instance.upload_files,
        }

    def wait_for_instances(self, sleep_time: int = 60):
        """Wait for instances to be ready"""
        logger.info(
            f"Going to Sleep for {sleep_time} seconds to make sure the instances are up"
        )
        time.sleep(sleep_time)
