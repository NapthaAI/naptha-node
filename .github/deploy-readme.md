# Application Deployment Workflow

This repository contains a GitHub Actions workflow for automated deployment to an Amazon EC2 instance. The workflow is triggered either by pushing to the `main` or when a pull request to merged to main.

## Workflow Overview

The deployment workflow automates the following steps:
1. Checks out the repository
2. Sets up SSH access to the EC2 instance
3. Deploys the application to EC2
4. Reports the deployment status

## Prerequisites

### Initial Server Setup
Before using this workflow, you must manually set up each EC2 instance:

1. Launch Ubuntu EC2 instances
2. Set up the deployment environment on each instance:
   - Clone the repository to the target deployment path
   - Create and configure the `.env` file with required environment variables
   - Install all necessary dependencies (Node.js, Python, etc.)
   - Ensure `launch.sh` and `stop_service.sh` are executable (`chmod +x *.sh`)
   - Test the application manually to verify the environment is properly configured

### GitHub Configuration
After server setup, configure the following GitHub repository secrets:

1. For single instance deployment:
   - `EC2_SSH_KEY`: The private SSH key for connecting to the EC2 instance
   - `EC2_HOST`: The hostname or IP address of your EC2 instance
   - `DEPLOY_PATH`: The path on the EC2 instance where the application is deployed

2. For dual instance deployment:
   - `EC2_SSH_KEY`: The private SSH key (same key for both instances)
   - `EC2_HOST_1`: The hostname/IP for the first EC2 instance
   - `EC2_HOST_2`: The hostname/IP for the second EC2 instance
   - `DEPLOY_PATH`: The deployment path (must be same on both instances)

## Trigger Conditions

The workflow triggers under two conditions:
- On push to the `main` branch
- When a pull request to the `main` branch is merged

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
- Code is pushed to the `main` branch
- A pull request to the `main` branch is merged

## Monitoring

You can monitor deployments in the GitHub Actions tab of your repository. Each deployment will show:
- Complete logs of the deployment process
- Final deployment status (✅ success or ❌ failure)

## Note

The workflow is configured to deploy from the `main` branch. All deployments will happen either through direct pushes to `main` or when pull requests are merged into `main`.

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
