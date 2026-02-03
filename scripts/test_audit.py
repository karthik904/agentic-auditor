# scripts/test_audit.py
import requests
import json
import time

BASE_URL = "http://localhost:8000"

def test_health():
    """Test health endpoint"""
    print("Testing health endpoint...")
    response = requests.get(f"{BASE_URL}/health")
    print(f"Status: {response.status_code}")
    print(f"Response: {response.json()}")
    return response.status_code == 200

def create_audit_job():
    """Create a test audit job"""
    print("\nCreating audit job...")
    
    # For Azure (replace with your subscription ID)
    payload = {
        "cloud_provider": "azure",
        "subscription_id": "test-subscription",  # Replace with actual ID
        "checks": ["security", "compliance"],
        "priority": "medium"
    }
    
    # For AWS
    # payload = {
    #     "cloud_provider": "aws",
    #     "account_id": "123456789012",
    #     "checks": ["security"],
    #     "priority": "high"
    # }
    
    response = requests.post(f"{BASE_URL}/audit", json=payload)
    
    if response.status_code == 200:
        job = response.json()
        print(f"Job created: {job['job_id']}")
        return job['job_id']
    else:
        print(f"Failed to create job: {response.text}")
        return None

def check_job_status(job_id):
    """Check job status"""
    print(f"\nChecking job {job_id}...")
    
    # Wait a bit for processing
    time.sleep(2)
    
    response = requests.get(f"{BASE_URL}/jobs/{job_id}")
    
    if response.status_code == 200:
        status = response.json()
        print(f"Job status: {status['status']}")
        print(f"Findings count: {status.get('findings_count', 0)}")
        return status
    else:
        print(f"Failed to get job status: {response.text}")
        return None

def get_metrics():
    """Get system metrics"""
    print("\nGetting system metrics...")
    response = requests.get(f"{BASE_URL}/metrics")
    
    if response.status_code == 200:
        metrics = response.json()
        print(f"Queue status: {metrics['queues']}")
        print(f"Jobs: {metrics['jobs']}")
        print(f"Findings: {metrics['findings']}")
        return metrics
    else:
        print(f"Failed to get metrics: {response.text}")
        return None

if __name__ == "__main__":
    print("🧪 Testing Agentic Cloud Auditor")
    print("=" * 40)
    
    # Test 1: Health check
    if not test_health():
        print("❌ Health check failed")
        exit(1)
    
    print("✅ Health check passed")
    
    # Test 2: Create audit job
    job_id = create_audit_job()
    if not job_id:
        print("❌ Failed to create audit job")
        exit(1)
    
    print("✅ Audit job created")
    
    # Test 3: Check job status (multiple times)
    for i in range(5):
        status = check_job_status(job_id)
        if status and status['status'] == 'completed':
            print("✅ Job completed successfully")
            break
        time.sleep(3)
    
    # Test 4: Get findings
    if job_id:
        response = requests.get(f"{BASE_URL}/jobs/{job_id}/findings")
        if response.status_code == 200:
            findings = response.json()
            print(f"\n📋 Found {len(findings['findings'])} findings")
            for finding in findings['findings'][:3]:  # Show first 3
                print(f"  - {finding['severity'].upper()}: {finding['description'][:100]}...")
    
    # Test 5: Get metrics
    get_metrics()
    
    print("\n🎉 All tests completed!")