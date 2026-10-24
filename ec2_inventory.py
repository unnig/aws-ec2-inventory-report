"""Export EC2 instance details for the configured AWS region to a CSV file."""

import csv
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import (
    BotoCoreError,
    ClientError,
    NoCredentialsError,
    PartialCredentialsError,
)


OUTPUT_FILE = Path("ec2_instance_report.csv")
CSV_FIELDS = (
    "Instance ID",
    "Instance Name",
    "Instance State",
    "Instance Type",
    "Private IP Address",
    "Public IP Address",
    "Availability Zone",
    "Launch Time",
)

logger = logging.getLogger(__name__)


def get_instance_name(tags: list[dict[str, str]] | None) -> str:
    """Return the EC2 Name tag value, or an empty string if it is not set."""
    for tag in tags or []:
        if tag.get("Key") == "Name":
            return tag.get("Value", "")
    return ""


def collect_instances(ec2_client: Any) -> list[dict[str, str]]:
    """Retrieve all instances visible to the caller in the current region."""
    instances: list[dict[str, str]] = []
    paginator = ec2_client.get_paginator("describe_instances")

    for page in paginator.paginate():
        for reservation in page.get("Reservations", []):
            for instance in reservation.get("Instances", []):
                launch_time: datetime | None = instance.get("LaunchTime")
                instances.append(
                    {
                        "Instance ID": instance.get("InstanceId", ""),
                        "Instance Name": get_instance_name(instance.get("Tags")),
                        "Instance State": instance.get("State", {}).get("Name", ""),
                        "Instance Type": instance.get("InstanceType", ""),
                        "Private IP Address": instance.get("PrivateIpAddress", ""),
                        "Public IP Address": instance.get("PublicIpAddress", ""),
                        "Availability Zone": instance.get("Placement", {}).get(
                            "AvailabilityZone", ""
                        ),
                        "Launch Time": (
                            launch_time.isoformat() if launch_time else ""
                        ),
                    }
                )

    return instances


def write_csv(instances: list[dict[str, str]], output_file: Path) -> None:
    """Write instance records and a header row to a CSV file."""
    with output_file.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(instances)


def log_summary(instances: list[dict[str, str]]) -> None:
    """Log total, running, and stopped instance counts."""
    running_count = sum(
        instance["Instance State"] == "running" for instance in instances
    )
    stopped_count = sum(
        instance["Instance State"] == "stopped" for instance in instances
    )
    logger.info("Total EC2 instances found: %d", len(instances))
    logger.info("Running instances: %d", running_count)
    logger.info("Stopped instances: %d", stopped_count)


def main() -> int:
    """Collect EC2 instances, export them, and report a summary."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    session = boto3.Session()
    region = session.region_name
    if not region:
        logger.error(
            "No AWS region is configured. Run 'aws configure' or set AWS_DEFAULT_REGION."
        )
        return 1

    try:
        ec2_client = session.client("ec2", region_name=region)
        instances = collect_instances(ec2_client)
        write_csv(instances, OUTPUT_FILE)
    except (NoCredentialsError, PartialCredentialsError):
        logger.error(
            "AWS credentials are missing or incomplete. Configure them with "
            "'aws configure' or an approved credential provider."
        )
        return 1
    except ClientError as error:
        error_code = error.response.get("Error", {}).get("Code", "Unknown")
        if error_code in {
            "AccessDenied",
            "AccessDeniedException",
            "UnauthorizedOperation",
            "AuthFailure",
            "OperationNotPermitted",
        }:
            logger.error(
                "Permission denied while describing EC2 instances in %s. "
                "Grant the caller ec2:DescribeInstances permission. AWS error: %s",
                region,
                error_code,
            )
        else:
            logger.error("AWS API error in region %s (%s): %s", region, error_code, error)
        return 1
    except BotoCoreError as error:
        logger.error("AWS SDK error while retrieving EC2 instances: %s", error)
        return 1
    except OSError as error:
        logger.error("Could not write report to %s: %s", OUTPUT_FILE, error)
        return 1

    logger.info("Report written to %s", OUTPUT_FILE.resolve())
    log_summary(instances)
    return 0


if __name__ == "__main__":
    sys.exit(main())
