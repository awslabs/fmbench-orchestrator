from pathlib import Path
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field, field_validator
from fmbench_orchestrator.utils.yaml_utils import load_yaml_file
from fmbench_orchestrator.utils.logger import logger
from .models import MainConfig


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
