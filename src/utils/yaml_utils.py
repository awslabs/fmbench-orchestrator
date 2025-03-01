"""YAML utilities for configuration handling."""

import yaml
from typing import Dict, Any
from pathlib import Path


def normalize_yaml_param_spacing(template_content: str, variable_name: str) -> str:
    """
    Normalize the spacing in YAML templates for variable substitution.

    Args:
        template_content: The YAML template content
        variable_name: The variable name to normalize

    Returns:
        Normalized YAML content
    """
    lines = template_content.split("\n")
    normalized_lines = []

    for line in lines:
        if "{{" + variable_name + "}}" in line:
            # Get the indentation level
            indent = len(line) - len(line.lstrip())
            # Get the key name if it exists
            key_part = line.split(":")[0].strip() if ":" in line else None

            if key_part:
                # If there's a key, keep it in the replacement
                normalized_lines.append(
                    f"{' ' * indent}{key_part}: {{{{ {variable_name} }}}}"
                )
            else:
                # If no key, just use the variable
                normalized_lines.append(" " * indent + "{{" + variable_name + "}}")
        else:
            normalized_lines.append(line)

    return "\n".join(normalized_lines)


def get_rendered_yaml(config_file_path: str, context: Dict[str, Any]) -> str:
    """
    Render a YAML template with the given context.

    Args:
        config_file_path: Path to the YAML template file
        context: Dictionary of variables to substitute

    Returns:
        Rendered YAML content
    """
    template_path = Path(config_file_path)
    if not template_path.exists():
        raise FileNotFoundError(f"Template file not found: {config_file_path}")

    # Read the template content
    template_content = template_path.read_text()

    # Normalize spacing for each variable in the context
    for var_name in context:
        template_content = normalize_yaml_param_spacing(template_content, var_name)

    # Replace variables
    for key, value in context.items():
        template_content = template_content.replace("{{" + key + "}}", str(value))

    return template_content
