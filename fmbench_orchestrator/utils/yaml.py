"""YAML utilities for configuration handling."""
import re
import yaml
import os
import logging
import urllib.parse
import urllib.request
from pathlib import Path
from jinja2 import Template
from typing import Dict, Any, Optional
from fmbench_orchestrator.utils.logger import logger    
from fmbench_orchestrator.utils.aws_utils import get_region
from fmbench_orchestrator.utils.constants import CONSTANTS


def _normalize_yaml_param_spacing(template_content: str, variable_name: str) -> str:
    """
    Replaces all possible spacing combinations of '{{ gpu_ami}}' with '{{gpu_ami}}'.
    
    Parameters:
    - template_content (str): The content of the template with potential spacing around 'gpu_ami'.
    - param_name (str): The name of the parameter to fix spacing
    Returns:
    - str: The template content with normalized '{{gpu_ami}}' placeholders.
    """
    
    # Define the regex pattern to match '{{ gpu_ami}}' with any possible spacing
    pattern = r"\{\{\s*" + re.escape(variable_name) + r"\s*\}\}"
    
    # Replace all occurrences of the pattern with '{{gpu_ami}}'
    normalized_content = re.sub(pattern, f"{{{variable_name}}}", template_content)
    
    return normalized_content


def _get_rendered_yaml(config_file_path: str, context: Dict) -> str:
    """
    Renders a YAML template file with the provided context using Jinja2.

    Args:
        config_file_path (str): Path to the YAML template file to render.
        context (Dict): Dictionary containing variables to substitute in the template.
            Expected keys include 'region', 'config_file', and 'write_bucket'.

    Returns:
        str: The rendered YAML content with variables substituted.

    Note:
        Uses Jinja2 templating to replace variables like {{region}} with values from context.
        Normalizes spacing around template variables before rendering.
    """

    logger.info(f"config_file_path={config_file_path}")
    # read the yml file as raw text
    template_content = Path(config_file_path).read_text()

    # Normalize the spacing, so {{ gpu }} and {{ gpu}} etc all get converted
    # to {{gpu}}
    for param in ['gpu', 'cpu', 'neuron']:
        template_content = _normalize_yaml_param_spacing(template_content, param)

    # context contains region, config file etc.
    # context = {'region': global_region, 'config_file': fmbench_config_file, 'write_bucket': write_bucket}

    # First rendering to substitute 'region' and 'config_file'
    # if the {{config_file}} placeholder does not exist in the config.yml
    # then the 'config_file' key in the 'context' dict does not do anything
    # if the {{config_file}} placeholder does indeed exist then it will get
    # replaced with the value in the context dict, if however the user did not
    # provide the value as a command line argument to the orchestrator then it
    # would get replaced by None and we would have no fmbench config file and the 
    # code would raise an exception that it cannot continue
    template = Template(template_content)
    rendered_yaml = template.render(context)
    return rendered_yaml


def load_yaml_file(config_file_path: str,
                   ami_mapping_file_path: str,
                   fmbench_config_file: Optional[str],
                   infra_config_file: str,
                   write_bucket: Optional[str]) -> Optional[Dict]:  
    """
    Load and parse a YAML file using Jinja2 templating for region and AMI ID substitution.

    Args:
        file_path (str): The path to the YAML file to be read.

    Returns:
        Optional[Dict]: Parsed content of the YAML file as a dictionary with region and AMI mapping information
                        substituted, or None if an error occurs.
    """

    # mandatory files should be present
    for f in [config_file_path, ami_mapping_file_path, infra_config_file]:
        if Path(f).is_file() is False:
            logger.error(f"{f} not found, cannot continue")
            raise FileNotFoundError(f"file '{f}' does not exist.")
    
    # Get the global region where this orchestrator is running
    # Initial context with 'region'
    global_region = get_region()
    context = {'region': global_region, 'config_file': fmbench_config_file, 'write_bucket': write_bucket}

    rendered_yaml = _get_rendered_yaml(config_file_path, context)
    # yaml to json
    config_data = yaml.safe_load(rendered_yaml)

    rendered_yaml = _get_rendered_yaml(infra_config_file, context)
    # yaml to json
    infra_config_data = yaml.safe_load(rendered_yaml)

    # merge the two configs
    config_data = config_data | infra_config_data

    # Fetch the AMI mapping file
    ami_mapping =  yaml.safe_load(Path(ami_mapping_file_path).read_text())

    # at this time any instance of ami_id: ami-something would remain as is
    # but any instance ami_id: gpu have been converted to ami_id: {gpu: None}
    # so we will iterate through the instance to replace ami_id with region specific
    # ami_id values from the ami_mapping we have. We have to do this because jinja2 does not
    # support nested variables and all other options added unnecessary complexity
    for i, instance in enumerate(config_data['instances']):
        if instance.get('region') is None:
            config_data['instances'][i]['region'] = global_region
            region = global_region
        else:
            region = instance['region']
        ami_id = instance['ami_id']

        if isinstance(ami_id, dict):
            # name of the first key, could be gpu, cpu, neuron or others in future
            ami_key = next(iter(ami_id))
            ami_id_from_config = None
            if ami_mapping.get(region):
                ami_id_from_config = ami_mapping[region].get(ami_key)
                if ami_id_from_config is None:
                    logger.error(f"instance {i+1}, instance_type={instance['instance_type']}, no ami found for {region} type {ami_key}")
                    raise Exception(f"instance {i+1}, instance_type={instance['instance_type']}, no ami found for {region} type {ami_key}")
            else:
                logger.error(f"no info found for region {region} in {ami_mapping_file_path}, cannot continue")
                raise Exception(f"instance {i+1}, instance_type={instance['instance_type']}, no info found in region {region} in {ami_mapping_file_path}, cannot continue")
            logger.info(f"instance {i+1}, instance_type={instance['instance_type']}, ami_key={ami_key}, region={region}, ami_id_from_config={ami_id_from_config}")
            # set the ami id
            config_data['instances'][i]['ami_id'] = ami_id_from_config
        elif isinstance(ami_id, str):
            logger.info(f"instance {i+1}, instance_type={instance['instance_type']}, region={region}, ami_id={ami_id}")
        else:
            raise Exception(f"instance {i+1}, instance_type={instance['instance_type']}, "
                            f"no info found for ami_id {ami_id}, region {region} in {ami_mapping_file_path}, cannot continue")

        # see if we need to unfurl the fmbench config file url
        fmbench_config_paths = instance['fmbench_config']
        if isinstance(fmbench_config_paths, list):
            for j in range(len(fmbench_config_paths)):
                if fmbench_config_paths[j] is None or fmbench_config_paths[j] == 'None':
                    raise Exception(f"instance {i+1}, instance_type={instance['instance_type']}, "
                                    f"no fmbench_config file provided, cannot continue")

                if fmbench_config_paths[j].startswith(CONSTANTS.FMBENCH_CFG_PREFIX):
                    fmbench_config_paths[j] = fmbench_config_paths[j].replace(CONSTANTS.FMBENCH_CFG_PREFIX, CONSTANTS.FMBENCH_CFG_GH_PREFIX)
            config_data['instances'][i]['fmbench_config'] = fmbench_config_paths

    return config_data
