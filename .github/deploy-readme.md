# Application Deployment Workflow

This repository contains a GitHub Actions workflow for automated deployment to an Amazon EC2 instance. The workflow is triggered either by pushing to the `feat/deploy-actions` branch or when a pull request to this branch is merged.

## Workflow Overview

The deployment workflow automates the following steps:
1. Checks out the repository
2. Sets up SSH access to the EC2 instance
3. Deploys the application to EC2
4. Reports the deployment status

## Prerequisites

Before using this workflow, ensure you have the following setup:

1. An Amazon EC2 instance running Ubuntu
2. The following GitHub repository secrets configured:
   - `EC2_SSH_KEY`: The private SSH key for connecting to the EC2 instance
   - `EC2_HOST`: The hostname or IP address of your EC2 instance
   - `DEPLOY_PATH`: The path on the EC2 instance where the application should be deployed

## Trigger Conditions

The workflow triggers under two conditions:
- On push to the `feat/deploy-actions` branch
- When a pull request to the `feat/deploy-actions` branch is merged

## Deployment Process

The deployment process follows these steps:

1. **Repository Checkout**: Fetches the latest code from the repository
2. **SSH Setup**: 
   - Creates SSH directory
   - Installs the SSH private key
   - Adds the EC2 host to known hosts
3. **Application Deployment**:
   - Connects to EC2 via SSH
   - Navigates to the deployment directory
   - Stashes any local changes
   - Fetches and resets to the latest code
   - Attempts to reapply stashed changes
   - Stops the existing service
   - Launches the new version
4. **Status Reporting**: Reports whether the deployment was successful or failed

## Required Files

The workflow expects the following files to exist in your repository:
- `stop_service.sh`: Script to stop the currently running service
- `launch.sh`: Script to start the application

## Usage

No manual intervention is needed for deployment. The workflow will automatically run when:
- Code is pushed to the `feat/deploy-actions` branch
- A pull request to the `feat/deploy-actions` branch is merged

## Monitoring

You can monitor deployments in the GitHub Actions tab of your repository. Each deployment will show:
- Complete logs of the deployment process
- Final deployment status (✅ success or ❌ failure)

## Note

Currently, the workflow is configured to use the `feat/deploy-actions` branch. This will be updated to use the `main` branch once testing is completed.

## Troubleshooting

If deployment fails, check:
1. EC2 instance is running and accessible
2. SSH key is correctly configured in GitHub secrets
3. All required scripts (`stop_service.sh` and `launch.sh`) exist and are executable
4. Deployment path exists on the EC2 instance
5. GitHub Actions logs for specific error messages

## Security Considerations

- The SSH key is stored securely in GitHub secrets
- SSH key permissions are set to 600 (read/write for owner only)
- Host key verification is enabled for the EC2 instance
