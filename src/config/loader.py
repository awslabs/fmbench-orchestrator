import os
import yaml
from pathlib import Path
from typing import Dict, Any, Optional
from .models import MainConfig
from src.utils.logger import logger
from src.utils.constants import AMIType
from src.utils.yaml_utils import get_rendered_yaml


class ConfigLoader:
    def __init__(self, config_dir: str = "configs"):
        """
        Initialize the ConfigLoader.

        Args:
            config_dir: Directory containing configuration files
        """
        self.config_dir = Path(config_dir)

    def _load_yaml(self, file_path: Path) -> Dict[str, Any]:
        """
        Load a YAML file.

        Args:
            file_path: Path to the YAML file

        Returns:
            Dict containing the YAML contents
        """
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        with open(file_path) as f:
            return yaml.safe_load(f)

    def _render_template(
        self, config_data: Dict[str, Any], ami_mapping: Dict[str, Dict[str, str]]
    ) -> Dict[str, Any]:
        """
        Render the configuration template by replacing placeholders.

        Args:
            config_data: Raw configuration data
            ami_mapping: AMI mapping data

        Returns:
            Dict containing the rendered configuration
        """
        # Deep copy the config data to avoid modifying the original
        rendered_config = config_data.copy()

        # Get the region from AWS config
        region = rendered_config.get("aws", {}).get("region")
        if not region:
            raise ValueError("Region not specified in AWS configuration")

        # Get AMI mappings for the region
        region_ami_mapping = ami_mapping.get(region)
        if not region_ami_mapping:
            raise ValueError(f"No AMI mapping found for region: {region}")

        # Replace placeholders in instance configurations
        for instance in rendered_config.get("instances", []):
            # Replace region template
            if (
                isinstance(instance.get("region"), str)
                and "{{region}}" in instance["region"]
            ):
                instance["region"] = region

            # Replace AMI template
            ami_id = instance.get("ami_id")
            if isinstance(ami_id, str) and "{{" in ami_id and "}}" in ami_id:
                ami_type = ami_id.strip("{}").lower()
                if ami_type not in region_ami_mapping:
                    raise ValueError(f"Invalid AMI type: {ami_type}")
                instance["ami_id"] = region_ami_mapping[ami_type]

        # Also replace in defaults if they exist
        defaults = rendered_config.get("defaults", {})
        if (
            isinstance(defaults.get("region"), str)
            and "{{region}}" in defaults["region"]
        ):
            defaults["region"] = region

        if (
            isinstance(defaults.get("ami_id"), str)
            and "{{" in defaults["ami_id"]
            and "}}" in defaults["ami_id"]
        ):
            ami_type = defaults["ami_id"].strip("{}").lower()
            if ami_type not in region_ami_mapping:
                raise ValueError(f"Invalid AMI type: {ami_type}")
            defaults["ami_id"] = region_ami_mapping[ami_type]

        return rendered_config

    def load_config(
        self, config_file: str, ami_mapping_file: str = "ami_mapping.yml"
    ) -> MainConfig:
        """
        Load and validate the configuration.

        Args:
            config_file: Name of the main configuration file
            ami_mapping_file: Name of the AMI mapping file

        Returns:
            MainConfig: Validated configuration object
        """
        # Load the main config and AMI mapping
        config_path = self.config_dir / config_file
        ami_mapping_path = self.config_dir / ami_mapping_file

        try:
            # Load AMI mapping
            ami_mapping = self._load_yaml(ami_mapping_path)

            # Get region from AMI mapping
            region = next(iter(ami_mapping.keys()))  # Use first region as default

            # Create context for template rendering
            context = {
                "region": region,
                "gpu": ami_mapping[region]["gpu"],
                "neuron": ami_mapping[region]["neuron"],
                "cpu": ami_mapping[region]["cpu"],
            }

            # Use the YAML utilities to render the config
            rendered_config = get_rendered_yaml(str(config_path), context)
            logger.info("Rendered YAML:\n" + rendered_config)  # Print rendered YAML

            # Parse the rendered YAML
            config_data = yaml.safe_load(rendered_config)

            # Validate and create the configuration object
            config = MainConfig(**config_data)
            logger.info(f"Successfully loaded configuration from {config_file}")
            return config

        except Exception as e:
            logger.error(f"Error loading configuration: {str(e)}")
            raise
