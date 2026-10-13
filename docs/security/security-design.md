# Security design

- Roles are admin, analyst, reviewer, and viewer. Exports require `reports:export`. Patient names and member IDs require `phi:view`.
- Local authentication is a password hash and a JWT. It is the demo and test issuer. Cognito is defined in Terraform and is not yet the API's token validator.
- Agent tools accept no SQL. Model context is checked for patient-name and member-ID fields before a completion call.
- Raw 835 text is not written to processing errors or audit details.
- API errors return a code and a short message.
- S3 objects in the Terraform definition use a customer-managed KMS key and block public access. RDS is in private subnets and is not publicly accessible.
- ECS uses a task role. The task definition does not contain static AWS keys.
- `BEDROCK_PHI_APPROVED` defaults to false. This repository does not claim HIPAA compliance.
- Demo passwords and the local JWT secret must be replaced before any shared deployment. Production startup refuses demo mode, the default JWT secret, SQLite, and local file storage.

Do not apply `infrastructure/terraform` without an explicit decision to create billable AWS resources.
