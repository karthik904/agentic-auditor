-- init.sql
CREATE TABLE IF NOT EXISTS audit_jobs (
    job_id VARCHAR(50) PRIMARY KEY,
    cloud_provider VARCHAR(20) NOT NULL,
    subscription_id VARCHAR(100),
    account_id VARCHAR(100),
    project_id VARCHAR(100),
    status VARCHAR(20) DEFAULT 'pending',
    checks TEXT[],
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS audit_findings (
    id SERIAL PRIMARY KEY,
    job_id VARCHAR(50) REFERENCES audit_jobs(job_id),
    resource_id VARCHAR(200),
    resource_type VARCHAR(50),
    check_type VARCHAR(50),
    severity VARCHAR(20),
    description TEXT,
    recommendation TEXT,
    metadata JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_audit_findings_job_id ON audit_findings(job_id);
CREATE INDEX idx_audit_findings_created_at ON audit_findings(created_at);
CREATE INDEX idx_audit_findings_severity ON audit_findings(severity);