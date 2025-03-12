# GitHub Actions Deployment Documentation

This repository contains deployment workflows for both EC2 and A100 instances. The deployment process is automated through GitHub Actions and triggers on pushes or merged pull requests to the main branch.

## Prerequisites

### Deployment Path
All instances must use the standardized deployment path:
```
/home/ubuntu/naptha/naptha-node
```

### Server Requirements
- Ubuntu OS (recommended: Ubuntu 22.04 LTS)
- Docker and Docker Compose installed
- For A100 instances: Python with Miniforge environment
- Proper permissions set up for deployment path

## Initial Server Setup

### Create deployment directory:
```bash
mkdir -p /home/ubuntu/naptha/naptha-node
chown -R ubuntu:ubuntu /home/ubuntu/naptha
```

### Install dependencies:
```bash
# Docker and Docker Compose
sudo apt update
sudo apt install docker.io docker-compose
```

## SSH Authentication Setup

### For EC2 Instances (.pem method)
- Use your existing EC2 .pem key
- Add the content to GitHub Secrets as `EC2_SSH_KEY`

### For A100 Instances (SSH key method)

1. Generate deployment SSH key pair:
```bash
ssh-keygen -t ed25519 -C "github-actions-deploy"
# Save as 'github-actions-deploy'
```

2. Add public key to authorized_keys on each A100 instance:
```bash
cat github-actions-deploy.pub >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
```

## GitHub Secrets Configuration

### Required Secrets for EC2
- `EC2_SSH_KEY`: The .pem file content
- `EC2_HOST_1`: First EC2 instance hostname/IP
- `EC2_HOST_2`: Second EC2 instance hostname/IP
- `DEPLOY_PATH`: `/home/ubuntu/naptha/naptha-node`

### Required Secrets for A100
- `SSH_PRIVATE_KEY`: Content of github-actions-deploy private key
- `SSH_KNOWN_HOSTS`: Content of generated known_hosts entries
- `A100_HOST_1`: First A100 instance hostname/IP
- `A100_HOST_2`: Second A100 instance hostname/IP
- `A100_USER`: SSH username for A100 instances
- `A100_DEPLOY_PATH`: `/home/ubuntu/naptha/naptha-node`

## Repository Requirements

### Required Files
- `docker-compose.yml`: Docker services configuration
- `docker-ctl.sh`: Docker service management script
- `launch.sh`: Main deployment script

### File Permissions
```bash
chmod +x docker-ctl.sh launch.sh
```

## Workflow Operation

### Trigger Conditions
- Push to main branch
- Merged pull request to main branch

### Deployment Process

#### EC2 Deployment
- SSH connection using .pem key
- Code checkout and deployment
- Service restart

#### A100 Deployment
- SSH setup with generated keys
- Python environment activation
- Docker-based deployment:
  - Build containers
  - Service management
  - Launch application

## Monitoring and Troubleshooting

### Deployment Status
- Monitor in GitHub Actions tab
- Each instance shows separate status
- Success/failure indicators for each step

### Common Issues and Solutions

#### SSH Connection Failed
```bash
# Check SSH connection manually
ssh -i your-key.pem ubuntu@EC2_HOST
# or
ssh -i github-actions-deploy A100_USER@A100_HOST
```

#### Python Not Found (A100)
```bash
# Verify Python installation
which python
python --version
```

#### Docker Issues
```bash
# Check Docker status
sudo systemctl status docker
# Check Docker Compose
docker-compose --version
```

### Logging
- GitHub Actions provides detailed logs
- Instance-specific logs in `/var/log`
- Docker logs via `docker-ctl.sh logs`

## Security Considerations

### SSH Key Management
- Keys stored as GitHub Secrets
- Proper file permissions (600)
- Regular key rotation recommended

### Access Control
- Minimal required permissions
- Separate keys for different environments
- No sensitive data in repository

## Additional Notes

### Deployment Path Structure
```
/home/ubuntu/naptha/naptha-node/
├── docker-compose.yml
├── docker-ctl.sh
├── launch.sh
└── [other application files]
```
