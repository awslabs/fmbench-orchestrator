import uuid
import boto3
import logging
from constants import *
from datetime import datetime
from globals import get_region, get_account_identity
from botocore.exceptions import ClientError, NoCredentialsError, PartialCredentialsError

logger = logging.getLogger(__name__)


class DynamoDBHandler:
    """
    A handler class for managing AWS DynamoDB operations, including creating tables and inserting items.

    Attributes:
        table_name (str): The name of the DynamoDB table.
        region (str): The AWS region where the DynamoDB table is located.
        dynamodb (ServiceResource): The DynamoDB resource object.
        table (Table): The DynamoDB table instance.
    """

    def __init__(self, run_uid: str, table_name: str = DEFAULT_DYNAMODB_TABLE_NAME):
        """
        Initializes the DynamoDBHandler with the table name and AWS region.

        Args:
            table_name (str): The name of the DynamoDB table.
            region (str): The AWS region for the DynamoDB table.
        """
        self.table_name = table_name
        self.region = get_region()
        self.dynamodb = boto3.resource("dynamodb", region_name=self.region)
        self.table = self.get_or_create_table()
        self.run_uid = run_uid

    def get_or_create_table(self):
        """
        Attempts to retrieve the specified DynamoDB table. If the table does not exist,
        it creates a new table with on-demand billing and a composite primary key of 
        'run_uid' (partition key) and 'instance_uid' (sort key).

        Returns:
            Table: The DynamoDB table instance if successful, or None if IAM permissions are missing.
        """
        try:
            # Try to load the table (raises an exception if it doesn't exist)
            table = self.dynamodb.Table(self.table_name)
            table.load()
            logger.info(f"Table '{self.table_name}' already exists.")
        except (NoCredentialsError, PartialCredentialsError):
            logger.warning(
                "IAM permissions are not enabled or incomplete. Skipping table creation."
            )
            return None
        except ClientError as e:
            if e.response["Error"]["Code"] == "ResourceNotFoundException":
                logger.info(
                    f"Table '{self.table_name}' does not exist. Creating it now..."
                )
                table = self.dynamodb.create_table(
                    TableName=self.table_name,
                    KeySchema=[
                        {"AttributeName": "run_uid", "KeyType": "HASH"},
                        {"AttributeName": "timestamp", "KeyType": "RANGE"}
                    ],
                    AttributeDefinitions=[
                        {"AttributeName": "run_uid", "AttributeType": "S"},
                        {"AttributeName": "timestamp", "AttributeType": "S"}
                    ],
                    BillingMode="PAY_PER_REQUEST",
                )
                table.wait_until_exists()
                logger.info(f"Table '{self.table_name}' has been created.")
            else:
                logger.error(f"Unexpected error: {e}")
                raise e
        return table

    def insert_item(
        self,
        item_data: dict,
        execution_status: str,
        keys_to_include: list = DYNAMODB_KEY_LIST,
    ):
        """
        Inserts a subset of item_data into the DynamoDB table, along with an additional 'status' parameter.
        Automatically generates a unique 'UID' for the item and adds 'timestamp' and 'date' fields if they
        are not present. It also includes the AWS account ID.

        Args:
            item_data (dict): A dictionary containing the attributes for the item to insert,
                            excluding 'UID' as it will be generated automatically.
            keys_to_include (list): A list of keys to include from item_data in the DynamoDB item.
            status (str): The execution status to include in the item data.

        Raises:
            ClientError: If there is an issue inserting the item into the DynamoDB table.
        """
        if not self.table:
            logger.warning("Table not initialized. Item insertion skipped.")
            return

        # Filter item_data to include only specified keys
        filtered_data = {
            key: item_data[key] for key in keys_to_include if key in item_data
        }

        filtered_data["execution_status"] = execution_status
        filtered_data["run_uid"] = self.run_uid
        instance_uid = filtered_data["instance_uid"]
        # Add 'timestamp' and 'date' fields if not provided
        filtered_data.setdefault("timestamp", datetime.now().isoformat())
        filtered_data.setdefault("date", datetime.now().strftime("%Y-%m-%d"))

        # Retrieve AWS account ID and add it to filtered_data
        account_id = get_account_identity()
        if account_id:
            filtered_data["account_id"] = account_id
        else:
            logger.warning("Account ID could not be retrieved. Proceeding without it.")

        try:
            self.table.put_item(Item=filtered_data)
            logger.info(
                f"Inserted item with Instance UID {instance_uid}: {filtered_data}"
            )
        except ClientError as e:
            logger.error(f"Failed to insert item: {e}")
            raise e
