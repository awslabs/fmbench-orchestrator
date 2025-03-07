"""Instance management module for fmbench-orchestrator."""

import time
import json
from typing import List, Dict, Tuple
from botocore.exceptions import NoCredentialsError
from fmbench_orchestrator.utils.logger import logger
from fmbench_orchestrator.utils.aws import (
    get_iam_role,
    upload_and_run_script,
)
from fmbench_orchestrator.aws.security_group import get_sg_id
from fmbench_orchestrator.aws.ec2 import create_ec2_instance
from fmbench_orchestrator.utils.constants import FMBENCH_GH_REPO
from fmbench_orchestrator.schema.handler import ConfigHandler
from fmbench_orchestrator.schema.models import InstanceDetails
from fmbench_orchestrator.aws.key_pair import get_key_pair
from pydantic import BaseModel


class InstanceHandler(BaseModel):
    """Handler for managing EC2 instances"""

    config_handler: ConfigHandler
    instance_id_list: List[str] = []
    instance_details_map: Dict[str, InstanceDetails] = {}

    class Config:
        """Pydantic config"""

        arbitrary_types_allowed = True

    def deploy_instances(self, args) -> Tuple[List[str], Dict[str, Dict]]:
        """Deploy EC2 instances based on configuration"""
        logger.info("Deploying EC2 Instances")
        if not self.config_handler.run_steps.deploy_ec2_instance:
            return self.instance_id_list, {
                k: v.model_dump() for k, v in self.instance_details_map.items()
            }

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

        return self.instance_id_list, {
            k: v.model_dump() for k, v in self.instance_details_map.items()
        }

    def _deploy_single_instance(self, instance, idx: int, iam_arn: str, args):
        """Deploy a single EC2 instance"""
        region = instance.region or self.config_handler.aws_config.region
        startup_script = instance.startup_script
        logger.info(f"Region Set for instance is: {region}")

        if region is None:
            raise ValueError("Region is not provided in the configuration file.")
        user_data_script = self._prepare_user_data_script(
            startup_script, self.config_handler.get_hf_token(), args
        )
        
        if self.config_handler.run_steps.security_group_creation:
            logger.info("Creating Security Groups. getting them by name if they exist")
            sg_id = get_sg_id(region, self.config_handler)
    
    
        PRIVATE_KEY_FNAME, PRIVATE_KEY_NAME = get_key_pair(region, self.config_handler)
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
        instance_details = InstanceDetails(
            instance_id=instance_id,
            fmbench_config=instance.fmbench_config,
            post_startup_script=instance.post_startup_script,
            post_startup_script_params=instance.post_startup_script_params,
            fmbench_complete_timeout=instance.fmbench_complete_timeout,
            region=region,
            PRIVATE_KEY_FNAME=private_key_fname,
            upload_files=instance.upload_files,
            instance_name=f"instance_{instance_id}",  # Generate a default instance name
        )
        self.instance_details_map[instance_id] = instance_details

    def wait_for_instances(self, sleep_time: int = 60):
        """Wait for instances to be ready"""
        logger.info(
            f"Going to Sleep for {sleep_time} seconds to make sure the instances are up"
        )
        time.sleep(sleep_time)
