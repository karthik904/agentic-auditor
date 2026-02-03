# worker/worker.py
import os
import json
import time
import logging
import asyncio
import signal
import sys
from datetime import datetime
from typing import Dict, Any, List

import redis
from azure.identity import DefaultAzureCredential
from azure.mgmt.resource import ResourceManagementClient
import boto3
from botocore.exceptions import ClientError

# Configure logging
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class AuditWorker:
    def __init__(self, worker_id: str = None):
        self.worker_id = worker_id or f"worker_{os.getpid()}_{int(time.time())}"
        self.running = True
        
        # Setup signal handlers
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
        
        # Initialize Redis
        redis_host = os.getenv("REDIS_HOST", "localhost")
        redis_port = int(os.getenv("REDIS_PORT", "6379"))
        
        self.redis_client = redis.Redis(
            host=redis_host,
            port=redis_port,
            decode_responses=True,
            socket_connect_timeout=10,
            retry_on_timeout=True
        )
        
        # Initialize cloud clients
        self.azure_credential = None
        self.aws_session = None
        
        logger.info(f"Worker {self.worker_id} initialized")
    
    def signal_handler(self, signum, frame):
        logger.info(f"Received signal {signum}, shutting down...")
        self.running = False
    
    def initialize_cloud_clients(self, cloud_provider: str):
        """Lazy initialization of cloud clients"""
        if cloud_provider == "azure" and self.azure_credential is None:
            try:
                self.azure_credential = DefaultAzureCredential()
                logger.info("Azure credential initialized")
            except Exception as e:
                logger.error(f"Failed to initialize Azure credential: {e}")
                raise
        
        elif cloud_provider == "aws" and self.aws_session is None:
            try:
                # AWS credentials should be set via environment variables
                # AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION
                self.aws_session = boto3.Session()
                logger.info("AWS session initialized")
            except Exception as e:
                logger.error(f"Failed to initialize AWS session: {e}")
                raise
    
    async def process_task(self, task: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Process a single audit task"""
        findings = []
        
        try:
            cloud_provider = task.get("cloud_provider")
            check_type = task.get("check_type", "security")
            
            # Initialize cloud client
            self.initialize_cloud_clients(cloud_provider)
            
            if cloud_provider == "azure":
                findings = await self.audit_azure(task)
            elif cloud_provider == "aws":
                findings = await self.audit_aws(task)
            elif cloud_provider == "gcp":
                findings = await self.audit_gcp(task)
            else:
                logger.error(f"Unsupported cloud provider: {cloud_provider}")
                return []
            
            logger.info(f"Found {len(findings)} issues in {cloud_provider}")
            return findings
            
        except Exception as e:
            logger.error(f"Failed to process task {task.get('job_id')}: {e}")
            # Return error as finding
            return [{
                "resource_id": "system",
                "resource_type": "audit_task",
                "check_type": task.get("check_type", "unknown"),
                "severity": "high",
                "description": f"Audit failed: {str(e)}",
                "recommendation": "Check worker logs and cloud permissions",
                "metadata": {"error": str(e), "task": task}
            }]
    
    async def audit_azure(self, task: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Audit Azure resources"""
        findings = []
        subscription_id = task.get("subscription_id")
        
        if not subscription_id:
            return [{
                "resource_id": "azure",
                "resource_type": "subscription",
                "check_type": "configuration",
                "severity": "high",
                "description": "No subscription ID provided",
                "recommendation": "Provide a valid Azure subscription ID"
            }]
        
        try:
            # Initialize Azure client
            resource_client = ResourceManagementClient(
                self.azure_credential,
                subscription_id
            )
            
            # Check 1: List resource groups (basic connectivity test)
            try:
                resource_groups = list(resource_client.resource_groups.list())
                
                if not resource_groups:
                    findings.append({
                        "resource_id": subscription_id,
                        "resource_type": "subscription",
                        "check_type": "security",
                        "severity": "low",
                        "description": "No resource groups found in subscription",
                        "recommendation": "This might be a new subscription",
                        "metadata": {"subscription_id": subscription_id}
                    })
                else:
                    # Check for empty resource groups
                    for rg in resource_groups:
                        resources = list(resource_client.resources.list_by_resource_group(rg.name))
                        if not resources:
                            findings.append({
                                "resource_id": rg.id,
                                "resource_type": "resource_group",
                                "check_type": "cost",
                                "severity": "low",
                                "description": f"Resource group '{rg.name}' is empty",
                                "recommendation": "Consider deleting empty resource groups",
                                "metadata": {"resource_group": rg.name}
                            })
            
            except Exception as e:
                findings.append({
                    "resource_id": subscription_id,
                    "resource_type": "subscription",
                    "check_type": "connectivity",
                    "severity": "high",
                    "description": f"Cannot access subscription: {str(e)}",
                    "recommendation": "Check permissions and subscription validity",
                    "metadata": {"error": str(e)}
                })
            
            return findings
            
        except Exception as e:
            logger.error(f"Azure audit failed: {e}")
            raise
    
    async def audit_aws(self, task: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Audit AWS resources"""
        findings = []
        account_id = task.get("account_id")
        
        try:
            # Test AWS connectivity
            sts = self.aws_session.client('sts')
            
            # Get caller identity
            identity = sts.get_caller_identity()
            logger.info(f"AWS Identity: {identity['Arn']}")
            
            # Check S3 buckets
            s3 = self.aws_session.client('s3')
            try:
                buckets = s3.list_buckets()
                
                if not buckets.get('Buckets'):
                    findings.append({
                        "resource_id": identity.get('Account', 'unknown'),
                        "resource_type": "account",
                        "check_type": "configuration",
                        "severity": "low",
                        "description": "No S3 buckets found",
                        "recommendation": "This might be a new account",
                        "metadata": {"account_id": identity.get('Account')}
                    })
                else:
                    # Check for public buckets
                    for bucket in buckets['Buckets']:
                        try:
                            acl = s3.get_bucket_acl(Bucket=bucket['Name'])
                            for grant in acl.get('Grants', []):
                                grantee = grant.get('Grantee', {})
                                if grantee.get('URI') == 'http://acs.amazonaws.com/groups/global/AllUsers':
                                    findings.append({
                                        "resource_id": bucket['Name'],
                                        "resource_type": "s3_bucket",
                                        "check_type": "security",
                                        "severity": "high",
                                        "description": f"S3 bucket '{bucket['Name']}' is publicly accessible",
                                        "recommendation": "Review and restrict bucket permissions",
                                        "metadata": {"bucket_name": bucket['Name']}
                                    })
                                    break
                        except ClientError as e:
                            # Some buckets may not allow ACL checks
                            if 'AccessDenied' not in str(e):
                                findings.append({
                                    "resource_id": bucket['Name'],
                                    "resource_type": "s3_bucket",
                                    "check_type": "security",
                                    "severity": "medium",
                                    "description": f"Cannot check permissions for bucket '{bucket['Name']}': {str(e)}",
                                    "recommendation": "Ensure proper permissions for audit",
                                    "metadata": {"error": str(e), "bucket_name": bucket['Name']}
                                })
            
            except ClientError as e:
                findings.append({
                    "resource_id": identity.get('Account', 'unknown'),
                    "resource_type": "account",
                    "check_type": "permissions",
                    "severity": "high",
                    "description": f"Cannot list S3 buckets: {str(e)}",
                    "recommendation": "Grant S3:ListAllMyBuckets permission",
                    "metadata": {"error": str(e)}
                })
            
            return findings
            
        except Exception as e:
            logger.error(f"AWS audit failed: {e}")
            raise
    
    async def audit_gcp(self, task: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Audit GCP resources"""
        findings = []
        project_id = task.get("project_id")
        
        if not project_id:
            return [{
                "resource_id": "gcp",
                "resource_type": "project",
                "check_type": "configuration",
                "severity": "high",
                "description": "No project ID provided",
                "recommendation": "Provide a valid GCP project ID"
            }]
        
        # For GCP, we'll do basic checks
        # In production, you'd use google-cloud-resource-manager
        findings.append({
            "resource_id": project_id,
            "resource_type": "project",
            "check_type": "info",
            "severity": "info",
            "description": f"GCP project '{project_id}' audit placeholder",
            "recommendation": "Implement GCP SDK integration",
            "metadata": {"project_id": project_id}
        })
        
        return findings
    
    async def run(self):
        """Main worker loop"""
        logger.info(f"Worker {self.worker_id} starting...")
        
        while self.running:
            try:
                # Try to get a task from Redis (blocking pop)
                # Try high priority first, then medium, then low
                for priority in ['high', 'medium', 'low']:
                    queue_name = f"audit_queue_{priority}"
                    
                    # Non-blocking pop
                    task_data = self.redis_client.lpop(queue_name)
                    
                    if task_data:
                        task = json.loads(task_data)
                        logger.info(f"Processing task: {task.get('job_id')} ({priority} priority)")
                        
                        # Process the task
                        findings = await self.process_task(task)
                        
                        # Store findings in Redis
                        if findings:
                            for finding in findings:
                                finding["job_id"] = task.get("job_id")
                                finding["worker_id"] = self.worker_id
                                finding["processed_at"] = datetime.utcnow().isoformat()
                                
                                # Push to findings list
                                self.redis_client.lpush(
                                    f"findings:{task.get('job_id')}",
                                    json.dumps(finding)
                                )
                        
                        # Mark task as processed
                        processed_key = f"processed:{task.get('job_id')}:{task.get('check_type')}"
                        self.redis_client.setex(processed_key, 3600, "true")
                        
                        # Update metrics
                        self.redis_client.hincrby("worker_metrics", self.worker_id, 1)
                        
                        # Short break between tasks
                        await asyncio.sleep(0.1)
                        break
                
                # If no tasks, sleep a bit
                await asyncio.sleep(1)
                
            except redis.exceptions.ConnectionError as e:
                logger.error(f"Redis connection error: {e}")
                await asyncio.sleep(5)  # Wait before retry
                
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse task JSON: {e}")
                await asyncio.sleep(1)
                
            except Exception as e:
                logger.error(f"Unexpected error in worker loop: {e}")
                await asyncio.sleep(5)
        
        logger.info(f"Worker {self.worker_id} stopped")

async def main():
    # Get worker type from environment
    worker_type = os.getenv("WORKER_TYPE", "general")
    worker = AuditWorker(worker_id=f"{worker_type}_{os.getpid()}")
    
    try:
        await worker.run()
    except KeyboardInterrupt:
        logger.info("Shutdown requested")
    except Exception as e:
        logger.error(f"Worker crashed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    # Run the worker
    asyncio.run(main())