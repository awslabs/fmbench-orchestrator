import boto3
import logging
import uuid
from datetime import datetime
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

    def __init__(self, table_name: str, region: str):
        """
        Initializes the DynamoDBHandler with the table name and AWS region.

        Args:
            table_name (str): The name of the DynamoDB table.
            region (str): The AWS region for the DynamoDB table.
        """
        self.table_name = table_name
        self.region = region
        self.dynamodb = boto3.resource("dynamodb", region_name=region)
        self.table = self.get_or_create_table()

    def get_or_create_table(self):
        """
        Attempts to retrieve the specified DynamoDB table. If the table does not exist,
        it creates a new table with on-demand billing and a primary key of 'UID'.

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
                    KeySchema=[{"AttributeName": "UID", "KeyType": "HASH"}],
                    AttributeDefinitions=[
                        {"AttributeName": "UID", "AttributeType": "S"}
                    ],
                    BillingMode="PAY_PER_REQUEST",
                )
                table.wait_until_exists()
                logger.info(f"Table '{self.table_name}' has been created.")
            else:
                logger.error(f"Unexpected error: {e}")
                raise e
        return table

    def insert_item(self, item_data: dict):
        """
        Inserts an item into the DynamoDB table. Automatically generates a unique 'UID'
        for the item and adds 'timestamp' and 'date' fields if they are not present.

        Args:
            item_data (dict): A dictionary containing the attributes for the item to insert,
                              excluding 'UID' as it will be generated automatically.

        Raises:
            ClientError: If there is an issue inserting the item into the DynamoDB table.
        """
        if not self.table:
            logger.warning("Table not initialized. Item insertion skipped.")
            return

        # Generate a unique UID
        uid = str(uuid.uuid4())
        item_data["UID"] = uid

        # Add 'timestamp' and 'date' fields
        item_data.setdefault("timestamp", datetime.now().isoformat())
        item_data.setdefault("date", datetime.now().strftime("%Y-%m-%d"))

        try:
            self.table.put_item(Item=item_data)
            logger.info(f"Inserted item with UID {uid}: {item_data}")
        except ClientError as e:
            logger.error(f"Failed to insert item: {e}")
            raise e
