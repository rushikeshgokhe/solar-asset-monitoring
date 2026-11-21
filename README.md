# Cloud-Native Solar Asset Monitoring & Intelligent Incident Automation Platform

An end-to-end, serverless AWS platform that automates solar inverter telemetry generation, ingestion, anomaly detection, incident correlation, recovery tracking, notifications, and Jira maintenance ticket integration.

The platform demonstrates how cloud-native services, Python automation, Infrastructure as Code (IaC), and CI/CD can be combined to build a scalable and fault-tolerant monitoring solution for solar energy assets.

**Repository:** https://github.com/rushikeshgokhe/solar-asset-monitoring

---

## 1. Project Overview

Solar power plants contain multiple sites, inverters, and data loggers that continuously generate operational telemetry.

Monitoring these systems manually can be time-consuming. Issues such as zero power generation, abnormal inverter temperature, and missing telemetry may require investigation and maintenance intervention.

This project addresses that challenge by building an automated monitoring and incident management platform using AWS serverless services.

The platform simulates solar inverter telemetry, processes incoming CSV files, detects operational anomalies, groups related detections into incidents, tracks recovery, and sends notifications.

It also includes an asynchronous Jira integration workflow that automatically creates and tracks maintenance tickets from incident events.

### Project Objectives

- Automate solar telemetry generation and ingestion.
- Validate incoming telemetry data.
- Detect operational anomalies using Python-based rules.
- Correlate repeated anomaly detections into incidents.
- Track incident lifecycle and recovery.
- Store monitoring events and incidents in DynamoDB.
- Send incident notifications through Amazon SNS.
- Integrate Jira Cloud for maintenance ticket automation.
- Implement asynchronous processing using Amazon SQS.
- Manage infrastructure using Terraform.
- Automate testing and deployment using GitHub Actions and AWS OIDC.

---

## 2. System Architecture

The platform follows a serverless, event-driven architecture.

### Architecture Diagram

```mermaid
flowchart TB

    subgraph A["1. Telemetry Ingestion"]
        EB["Amazon EventBridge<br/>Optional Scheduled Trigger"]
        GEN["Telemetry Generator Lambda"]
        S3IN[("Amazon S3<br/>telemetry/")]

        EB --> GEN
        GEN --> S3IN
    end

    subgraph B["2. Incident Processing"]
        PROC["Telemetry Processor Lambda"]
        VALID["CSV Validation"]
        DETECT["Rule-Based Anomaly Detection"]
        NORMAL["15-Minute Incident Correlation"]
        RECOVERY["Recovery Evaluation"]

        S3OUT[("Amazon S3<br/>processed/")]
        DDB[("Amazon DynamoDB<br/>EVENT and INCIDENT")]
        SNS["Amazon SNS<br/>Email Notifications"]

        PROC --> VALID
        VALID --> DETECT
        DETECT --> NORMAL
        NORMAL --> RECOVERY
        RECOVERY --> S3OUT
        RECOVERY --> DDB
        RECOVERY --> SNS
    end

    S3IN -->|"S3 ObjectCreated Event"| PROC

    subgraph C["3. Asynchronous Ticket Automation"]
        QUEUE[["Amazon SQS<br/>Ticket Queue"]]
        TICKET["Ticket Processor Lambda"]
        SSM[("AWS SSM Parameter Store<br/>SecureString")]
        JIRA["Jira Cloud REST API"]

        QUEUE --> TICKET
        TICKET --> SSM
        TICKET --> JIRA
        TICKET <-->|"Ticket State and Idempotency"| DDB
        QUEUE -.->|"After 3 Retries"| DLQ2[["Ticket Dead-Letter Queue"]]
    end

    RECOVERY -->|"Incident Events"| QUEUE

    subgraph D["4. Monitoring and Failure Handling"]
        CW["Amazon CloudWatch<br/>Logs and Metrics"]
        ALARM["CloudWatch Error Alarm"]
        DLQ1[["Processor Dead-Letter Queue"]]

        PROC -.-> DLQ1
        GEN --> CW
        PROC --> CW
        TICKET --> CW
        CW --> ALARM
        ALARM --> SNS
    end
```

### High-Level Workflow

1. A telemetry generator creates simulated solar inverter readings.
2. The generated CSV file is uploaded to Amazon S3.
3. An S3 event triggers the telemetry processor Lambda.
4. The processor validates the incoming CSV data.
5. Python detection rules identify operational anomalies.
6. The incident normalizer groups related detections within a 15-minute correlation window.
7. DynamoDB stores monitoring events and incident information.
8. Recovery logic evaluates whether previously detected incidents have recovered.
9. Amazon SNS sends email notifications.
10. Incident events are placed into an SQS queue for asynchronous ticket processing.
11. The ticket processor integrates with Jira Cloud and creates or updates maintenance issues.
12. Ticket processing state is persisted in DynamoDB.
13. CloudWatch monitors execution and errors.
14. Failed ticket messages are routed to a dead-letter queue after three receive attempts.

EventBridge can optionally trigger scheduled telemetry generation.

---

## 3. Technology Stack

| Category | Technologies |
|---|---|
| Cloud Platform | Amazon Web Services (AWS) |
| Compute | AWS Lambda |
| Storage | Amazon S3 |
| Database | Amazon DynamoDB |
| Messaging | Amazon SQS |
| Notifications | Amazon SNS |
| Scheduling | Amazon EventBridge |
| Monitoring | Amazon CloudWatch |
| Secrets Management | AWS Systems Manager Parameter Store |
| Programming | Python |
| Ticket Management | Jira Cloud REST API |
| Infrastructure as Code | Terraform |
| CI/CD | GitHub Actions |
| Authentication | GitHub Actions OIDC |
| Testing | Pytest |
| Version Control | Git and GitHub |

---

## 4. Core System Components

### 4.1 Telemetry Generation

The project uses Python to generate simulated solar inverter telemetry.

The generated dataset represents multiple solar sites and inverters.

**Simulated environment:**

- 4 solar sites.
- 3 inverters per site.
- 12 inverters in total.
- 5-minute telemetry intervals.
- CSV-based telemetry ingestion.

Each telemetry record contains operational parameters such as:

- Timestamp
- Site ID
- Inverter ID
- AC power
- Irradiance (GHI)
- Inverter temperature
- Operational readings

The generated CSV files are uploaded to the S3 telemetry prefix.

**Note:** Telemetry is simulated for this portfolio project. It is not collected from live solar inverter hardware or a production monitoring API.

### 4.2 CSV Validation

Before anomaly detection, incoming CSV data is validated.

The validation process checks:

- Required columns.
- Data formats.
- Timestamp information.
- Missing or invalid values.
- Data consistency.

Invalid records are handled according to the processing logic rather than being treated as valid telemetry.

### 4.3 Anomaly Detection

The processor uses Python-based, rule-driven detection logic to identify abnormal operating conditions.

Three anomaly categories are implemented.

| Anomaly | Detection Condition | Severity |
|---|---|---|
| ZERO_POWER | GHI >= 200 W/m² and AC power <= 1 kW | HIGH |
| HIGH_TEMPERATURE | Inverter temperature >= 80°C | HIGH |
| MISSING_TELEMETRY | Telemetry gap greater than 5 minutes | MEDIUM |

These rules identify potential operational issues requiring investigation.

The detection engine uses predefined thresholds and does not use machine learning or AI-based prediction.

### 4.4 Incident Correlation and Normalization

Repeated detections of the same anomaly should not necessarily generate separate maintenance incidents.

The platform implements a 15-minute correlation window to group related anomaly detections.

This helps prevent duplicate incident creation when the same operational problem continues across multiple telemetry batches.

The system also distinguishes between an ongoing anomaly and a new occurrence after the previous incident has recovered.

### 4.5 Incident Lifecycle Management

The platform maintains an incident lifecycle:

**NEW → OPEN → RESOLVED**

- **NEW:** An anomaly is initially identified.
- **OPEN:** The anomaly is recognized as an active incident.
- **RESOLVED:** Recovery conditions are satisfied.

The recovery logic evaluates consecutive healthy telemetry readings before resolving an incident.

This prevents an incident from being marked resolved immediately after a single normal reading.

### 4.6 DynamoDB Event and Incident Storage

Amazon DynamoDB is used to store monitoring events and incident records.

The data model separates:

- EVENT records: Individual anomaly detection events.
- INCIDENT records: Normalized incident information and lifecycle state.

The implementation uses structured partition and sort keys to organize related records.

DynamoDB conditional and transactional operations support duplicate protection and consistent incident updates.

### 4.7 Idempotency and Duplicate Protection

Event-driven systems may process the same input more than once.

The project implements duplicate protection to reduce repeated event storage and unnecessary ticket processing.

Idempotency logic helps ensure that replayed telemetry or duplicate processing does not create unnecessary duplicate records or maintenance actions.

### 4.8 Recovery Tracking

The recovery module evaluates whether an active anomaly has returned to normal operating conditions.

It uses consecutive healthy readings to determine when an incident can be resolved.

Recovery events are recorded so that incident history and state changes can be tracked.

### 4.9 Jira Cloud Integration

The platform integrates with Jira Cloud for automated maintenance ticket management.

The integration was verified end-to-end against the Jira Cloud project with project key **KAN**.

Maintenance tasks were automatically created from incident events received through the SQS ticket-processing workflow.

**Verified Jira issues:**

| Jira Issue | Incident | Severity |
|---|---|---|
| KAN-5 | ZERO_POWER - SITE-104 - INV-03 | HIGH |
| KAN-6 | HIGH_TEMPERATURE - SITE-102 - INV-01 | HIGH |

The integration workflow uses:

- Jira Cloud REST API.
- Ticket Processor Lambda.
- Amazon SQS.
- AWS Systems Manager Parameter Store.
- DynamoDB ticket-state tracking.

Jira API credentials are stored as SecureString parameters in AWS Systems Manager Parameter Store rather than being hardcoded in the application.

The ticket processor creates maintenance issues and persists the corresponding ticket information and processing state in DynamoDB.

### 4.10 Amazon SNS Notifications

Amazon SNS is used to send email notifications containing incident processing summaries.

Notifications include relevant processing information, such as:

- Source S3 object.
- Number of processed records.
- Number of skipped records.
- Detected anomaly categories.
- Incident information.

CloudWatch alarm notifications can also be routed through SNS.

### 4.11 Amazon SQS and Dead-Letter Queues

Amazon SQS separates incident processing from ticket automation.

This allows the ticket processor to handle messages independently of the telemetry processor.

The implementation includes a ticket dead-letter queue with a redrive policy configured for three receive attempts.

Messages that cannot be processed successfully are routed to the dead-letter queue for investigation.

A separate dead-letter queue is also configured for telemetry processor failures.

This improves fault isolation and makes failures easier to investigate.

---

## 5. AWS Infrastructure

The platform uses the following AWS services:

| AWS Service | Responsibility |
|---|---|
| Amazon S3 | Stores raw telemetry and processed output |
| AWS Lambda | Executes telemetry generation, processing and ticket automation |
| Amazon DynamoDB | Stores events, incidents and ticket state |
| Amazon SQS | Handles asynchronous ticket messages |
| Amazon SNS | Sends email notifications |
| Amazon EventBridge | Supports scheduled telemetry generation |
| Amazon CloudWatch | Collects logs and monitors errors |
| AWS Systems Manager Parameter Store | Securely stores Jira credentials |
| AWS IAM | Controls service permissions |

**AWS Region:** `ap-south-1` (Asia Pacific - Mumbai)

The application infrastructure is managed through Terraform.

---

## 6. Infrastructure as Code with Terraform

Terraform is used to provision and manage AWS infrastructure.

Infrastructure configuration covers the resources required by the application, including:

- S3 buckets.
- Lambda functions and IAM roles.
- DynamoDB tables.
- SQS queues and dead-letter queues.
- SNS topics and subscriptions.
- CloudWatch monitoring and alarms.
- Event-driven service permissions.

### Terraform Benefits

- Infrastructure is defined as code.
- Resources can be recreated consistently.
- Configuration changes can be reviewed before deployment.
- Infrastructure can be deployed and destroyed when required.
- Manual AWS console configuration is reduced.

### Terraform State Management

A separate S3 backend is used for Terraform remote state management.

The backend configuration uses S3 state storage and native state locking.

The Terraform bootstrap resources are managed separately from the application infrastructure.

---

## 7. CI/CD Pipeline

The project uses GitHub Actions to automate validation and infrastructure deployment.

Three workflows are maintained:

| Workflow | Purpose |
|---|---|
| `ci.yml` | Runs automated tests and Terraform validation |
| `deploy.yml` | Deploys infrastructure through GitHub Actions |
| `destroy.yml` | Supports controlled infrastructure teardown |

### CI Pipeline

The CI workflow performs:

1. Python environment setup.
2. Dependency installation.
3. Pytest execution.
4. Terraform formatting checks.
5. Terraform initialization and validation.
6. Terraform planning.

### Deployment Pipeline

The deployment workflow uses GitHub Actions with AWS OIDC authentication.

This avoids storing long-lived AWS access keys in GitHub repository secrets.

The workflow obtains temporary AWS credentials through an IAM role configured for GitHub Actions.

### Infrastructure Teardown

A separate workflow supports controlled infrastructure destruction.

This helps avoid unnecessary AWS resource usage when the project is not being demonstrated or tested.

---

## 8. Project Structure

The repository is organized into separate modules for telemetry generation, incident processing, ticket automation, data, infrastructure, and testing.

```text
solar-asset-monitoring/
│
├── .github/
│   └── workflows/
│       ├── ci.yml
│       ├── deploy.yml
│       └── destroy.yml
│
├── src/
│   ├── generator/
│   │   └── Telemetry generation modules
│   │
│   ├── processor/
│   │   └── Telemetry validation, anomaly detection,
│   │       incident correlation and recovery modules
│   │
│   └── ticket_processor/
│       └── Jira ticket automation modules
│
├── data/
│   └── Telemetry datasets
│
├── terraform/
│   └── AWS infrastructure configuration
│
├── tests/
│   └── Automated test modules
│
├── reports/
│   └── screenshots/
│       ├── 06-jira-ticket-kan5.png
│       └── 07-jira-ticket-kan6.png
│
├── requirements.txt
├── requirements-dev.txt
├── pytest.ini
├── .gitignore
└── README.md
```

---

## 9. Sample Processing Results

The project was tested using simulated solar telemetry.

### Historical Dataset Verification

A historical test dataset contained:

| Metric | Result |
|---|---:|
| Telemetry records | 3,452 |
| Solar sites | 4 |
| Inverters | 12 |
| ZERO_POWER detections | 12 |
| HIGH_TEMPERATURE detections | 12 |
| MISSING_TELEMETRY detections | 1 |
| Total raw anomaly detections | 25 |

The 25 raw anomaly detections were grouped into normalized incident records according to the correlation logic.

### Example Anomaly Conditions

**ZERO_POWER**

- Solar irradiance is sufficiently high.
- Inverter AC power is near zero.
- Indicates a possible generation or inverter issue.

**HIGH_TEMPERATURE**

- Inverter temperature reaches or exceeds the configured threshold.
- Indicates a potential overheating condition.

**MISSING_TELEMETRY**

- Expected telemetry is not received within the configured interval.
- Indicates a possible communication or data collection issue.

---

## 10. Reliability and Fault Handling

Reliability is an important part of the platform.

The implementation includes:

- Event-driven processing.
- Incident correlation.
- Duplicate event protection.
- Recovery tracking.
- Asynchronous ticket processing.
- SQS retry handling.
- Dead-letter queues.
- CloudWatch logging.
- Error alarm notifications.

These mechanisms help the platform handle duplicate events, processing failures, and temporary downstream service issues.

---

## 11. Automated Testing

Pytest is used to test the Python application logic.

The test suite covers important areas such as:

- Telemetry validation.
- Anomaly detection.
- Incident normalization.
- Incident correlation.
- Incident repository operations.
- Duplicate event handling.
- Recovery evaluation.
- Ticket processing logic.

**Latest recorded verification:** 61 tests passed.

Run the tests locally using:

```powershell
python -m pytest -v
```

For a concise result:

```powershell
python -m pytest -q
```

---

## 12. Deployment

The infrastructure is deployed using Terraform and GitHub Actions.

The general deployment process is:

1. Clone the GitHub repository.
2. Configure the required Terraform variables.
3. Configure the AWS OIDC role and GitHub repository permissions.
4. Initialize Terraform.
5. Review the Terraform plan.
6. Apply the infrastructure.
7. Configure required notification subscriptions and application parameters.
8. Execute the telemetry processing workflow.
9. Review Lambda logs, DynamoDB records, S3 outputs and SNS notifications.

### Clone the Repository

```powershell
git clone https://github.com/rushikeshgokhe/solar-asset-monitoring.git
```

```powershell
cd solar-asset-monitoring
```

### Terraform Commands

```powershell
terraform init
```

```powershell
terraform fmt -recursive
```

```powershell
terraform validate
```

```powershell
terraform plan
```

```powershell
terraform apply
```

The actual deployment must follow the repository's Terraform backend, variable and workflow configuration.

---

## 13. Verification and Execution Evidence

The platform has been exercised through AWS deployments, live Jira integration and automated testing.

The following are recorded verification results from previous execution sessions.

### AWS Processing Verification

- S3-based telemetry ingestion.
- Lambda-based CSV processing.
- Anomaly detection.
- Incident normalization.
- DynamoDB persistence.
- SNS email notification.
- Asynchronous SQS ticket workflow.
- CloudWatch execution monitoring.

### November 19, 2026 - SNS Notification Evidence

A successfully processed telemetry batch generated an SNS email notification.

| Metric | Result |
|---|---:|
| Rows processed | 12 |
| Rows skipped | 0 |
| Anomaly records | 2 |
| HIGH_TEMPERATURE | 1 |
| ZERO_POWER | 1 |
| Normalized OPEN incidents | 2 |

The two incidents were:

- SITE-102 / INV-01 — HIGH_TEMPERATURE
- SITE-104 / INV-03 — ZERO_POWER

This execution demonstrates telemetry processing, anomaly detection, incident normalization and SNS email notification.

### November 21, 2026 - Live Jira Ticket Creation Evidence

The Jira integration was verified through actual maintenance ticket creation in Jira Cloud.

Two maintenance issues were automatically created from solar incident events through the `solar-monitoring-ticket-processor` Lambda.

| Jira Issue | Automatically Created Incident | Severity |
|---|---|---|
| KAN-5 | ZERO_POWER - SITE-104 - INV-03 | HIGH |
| KAN-6 | HIGH_TEMPERATURE - SITE-102 - INV-01 | HIGH |

**Execution workflow:**

1. Solar incident events were sent to the SQS ticket queue.
2. The ticket processor Lambda consumed the messages.
3. The processor integrated with the Jira Cloud REST API.
4. Jira issues KAN-5 and KAN-6 were created.
5. The corresponding ticket information and processing state were persisted in DynamoDB.

This demonstrates the integration between AWS event-driven processing, asynchronous ticket automation, Jira Cloud and DynamoDB persistence.

### Additional Recorded Tests

Other recorded verification scenarios covered:

- Cross-batch incident correlation.
- New incident creation after a previous incident was resolved.
- Duplicate event replay handling.
- Recovery state transitions.
- SQS message processing and queue draining.
- Dead-letter queue monitoring.

These results represent previous verification runs, not a claim that the AWS application stack is currently deployed.

---

## 14. Screenshots

The following screenshots provide visual evidence of Jira maintenance ticket creation.

| Screenshot | Description |
|---|---|
| `06-jira-ticket-kan5.png` | Jira issue KAN-5 - ZERO_POWER incident |
| `07-jira-ticket-kan6.png` | Jira issue KAN-6 - HIGH_TEMPERATURE incident |

**Screenshot directory:**

```text
reports/screenshots/
```

The Jira screenshots demonstrate successful maintenance ticket creation through the automated integration workflow.

---

## 15. Security

Security is addressed through AWS IAM, OIDC and secure credential storage.

### Implemented Security Practices

- IAM roles for AWS service permissions.
- Least-privilege access where configured.
- GitHub Actions OIDC authentication.
- No long-lived AWS access keys required in GitHub Actions.
- Jira credentials stored using SSM Parameter Store SecureString.
- Sensitive files excluded through `.gitignore`.
- Terraform variables used for environment-specific configuration.

---

## 16. Cost Management

The project uses serverless AWS services to avoid maintaining continuously running compute infrastructure.

Cost-conscious design choices include:

- Lambda-based execution.
- S3 storage.
- DynamoDB on-demand billing.
- SQS-based asynchronous processing.
- Infrastructure teardown after testing.
- Avoiding unnecessary scheduled executions.

### Infrastructure Teardown

The application infrastructure was intentionally destroyed after testing to reduce ongoing AWS costs.

The Terraform bootstrap resources used for remote state management and deployment may be managed separately.

CloudWatch log groups and retained data may also remain after application resources are destroyed.

---

## 17. Engineering Challenges

Some of the important engineering challenges addressed during development include:

### Duplicate Event Processing

Event-driven systems may process the same event more than once.

The solution uses idempotency and DynamoDB conditional operations to reduce duplicate processing.

### Incident Correlation

A continuous anomaly can generate multiple detections across different telemetry batches.

The 15-minute correlation window groups related detections into a single ongoing incident.

### Incident Recovery

An incident should not be resolved simply because one healthy reading is received.

The recovery module evaluates consecutive healthy readings before changing the incident state.

### Asynchronous Ticket Processing

Ticket creation should not block telemetry processing.

Amazon SQS decouples ticket automation from the main processing workflow.

### Secure Authentication

Long-lived AWS credentials should not be stored in GitHub Actions.

OIDC authentication provides temporary credentials through an IAM role.

### Infrastructure Cost Control

Cloud resources should not remain active unnecessarily.

Terraform and a dedicated teardown workflow support controlled infrastructure lifecycle management.

---

## 18. Business Value

The platform demonstrates how automated monitoring can improve operational workflows for solar energy assets.

Potential benefits include:

- Reduced manual telemetry review.
- Faster identification of operational anomalies.
- Centralized incident tracking.
- Reduced duplicate incident creation.
- Improved recovery visibility.
- Automated email notifications.
- Structured maintenance ticket workflows.
- Better monitoring and failure investigation.

The project is a simulated portfolio implementation and does not claim measured production cost savings or operational performance improvements.

---

## 19. Learning Outcomes

Through this project, I gained practical experience with:

- AWS serverless architecture.
- Amazon S3 event notifications.
- AWS Lambda development.
- Python automation.
- DynamoDB data modeling.
- Event-driven application design.
- Amazon SQS and dead-letter queues.
- Amazon SNS notifications.
- CloudWatch monitoring.
- IAM permissions and OIDC authentication.
- Terraform infrastructure management.
- GitHub Actions CI/CD.
- Jira Cloud REST API integration.
- Automated testing using Pytest.
- Incident lifecycle and recovery management.

---

## 20. Limitations and Future Enhancements

The current project uses simulated telemetry and predefined anomaly detection rules.

Possible future enhancements include:

- Integration with real solar inverter and data logger APIs.
- Live telemetry ingestion.
- Advanced anomaly detection using machine learning.
- Predictive maintenance.
- Grafana or other operational dashboards.
- Multi-region infrastructure support.
- Advanced incident analytics.
- More extensive end-to-end integration testing.

---

## 21. Project Summary

The Cloud-Native Solar Asset Monitoring & Intelligent Incident Automation Platform demonstrates an end-to-end cloud-native monitoring workflow using AWS, Python, Terraform and GitHub Actions.

It combines automated telemetry ingestion, rule-based anomaly detection, incident correlation, recovery tracking, event persistence, notifications and asynchronous Jira maintenance ticket automation.

The project focuses on practical Cloud Engineering concepts such as serverless computing, event-driven architecture, Infrastructure as Code, CI/CD, secure authentication, fault handling and automation.

---

## 22. Author

**Rushikesh V. Gokhe**

Electrical Engineering Graduate | Monitoring Analyst | Cloud & DevOps Engineering Aspirant

GitHub: https://github.com/rushikeshgokhe

Project Repository: https://github.com/rushikeshgokhe/solar-asset-monitoring
