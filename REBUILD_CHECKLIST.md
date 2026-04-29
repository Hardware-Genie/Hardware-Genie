# Hardware-Genie AWS Rebuild Checklist (Destroy + Re-Apply)

Use this checklist when you want a repeatable teardown and rebuild of the full stack.

## Fast Path (Scripts)

Use these scripts for one-command runs:

Destroy everything:

```powershell
Set-Location "c:\Users\manam\Desktop\4360 cs Senior Experience\Hardware-Genie"
.\scripts\terraform-destroy.ps1 -DbPassword "greatpassword"
```

Build everything:

```powershell
Set-Location "c:\Users\manam\Desktop\4360 cs Senior Experience\Hardware-Genie"
.\scripts\terraform-build.ps1 -DbPassword "greatpassword"
```

Build + run one-time seed:

```powershell
Set-Location "c:\Users\manam\Desktop\4360 cs Senior Experience\Hardware-Genie"
.\scripts\terraform-build.ps1 -DbPassword "greatpassword" -SeedAfterBuild
```

## Prerequisites

- AWS CLI authenticated for the correct account/region.
- Terraform installed.
- Run commands from this repo.
- Confirm the DB password you want to use (examples below use `greatpassword`).

PowerShell setup:

```powershell
$env:AWS_PAGER=""
Set-Location "c:\Users\manam\Desktop\4360 cs Senior Experience\Hardware-Genie"
```

---

## A) Destroy Day

### 1) Optional: Stop ECS service first (faster cleanup)

```powershell
aws ecs update-service --cluster hardware-genie-cluster --service hardware-genie-service --desired-count 0 --region us-west-1
```

### 2) Destroy modules in reverse dependency order

Destroy ECS:

```powershell
Set-Location ".\infra\ecs"
terraform init
terraform destroy --auto-approve -var "db_password=greatpassword"
```

Destroy Docker/ECR:

```powershell
Set-Location "..\docker"
terraform init
terraform destroy --auto-approve
```

Destroy RDS:

```powershell
Set-Location "..\rds"
terraform init
terraform destroy --auto-approve -var "db_password=greatpassword"
```

Destroy VPC/network:

```powershell
Set-Location "..\vpc"
terraform init
terraform destroy --auto-approve
```

### 3) Confirm everything is gone

```powershell
aws ecs list-clusters --region us-west-1
aws rds describe-db-instances --region us-west-1 --query "DBInstances[].DBInstanceIdentifier"
```

---

## B) Re-Apply Day

### 1) Recreate infrastructure in dependency order

Create VPC:

```powershell
Set-Location "c:\Users\manam\Desktop\4360 cs Senior Experience\Hardware-Genie\infra\vpc"
terraform init
terraform apply --auto-approve
```

Create RDS:

```powershell
Set-Location "..\rds"
terraform init
terraform apply --auto-approve -var "db_password=greatpassword"
```

Build/push Docker image (digest-pinned output):

```powershell
Set-Location "..\docker"
terraform init
terraform apply --auto-approve
```

Create ECS + ALB:

```powershell
Set-Location "..\ecs"
terraform init
terraform apply --auto-approve -var "db_password=greatpassword"
```

### 2) Verify service health

```powershell
aws ecs describe-services --cluster hardware-genie-cluster --services hardware-genie-service --region us-west-1 --query "services[0].{desired:desiredCount,running:runningCount,pending:pendingCount,taskDefinition:taskDefinition}"
```

Get ALB DNS:

```powershell
Set-Location "c:\Users\manam\Desktop\4360 cs Senior Experience\Hardware-Genie"
$tgArn=(aws ecs describe-services --cluster hardware-genie-cluster --services hardware-genie-service --region us-west-1 --query "services[0].loadBalancers[0].targetGroupArn" --output text)
$lbArn=(aws elbv2 describe-target-groups --target-group-arns $tgArn --region us-west-1 --query "TargetGroups[0].LoadBalancerArns[0]" --output text)
$albDns=(aws elbv2 describe-load-balancers --load-balancer-arns $lbArn --region us-west-1 --query "LoadBalancers[0].DNSName" --output text)
$albDns
```

Smoke test homepage:

```powershell
Invoke-WebRequest "http://$albDns/" -UseBasicParsing
```

---

## C) One-Time Data Seed After Fresh RDS

Because ECS service startup seeding is disabled by default (`SEED_SQLITE_TO_RDS=false`), run one one-off seed task after rebuild.

### 1) Create one-off override file

```powershell
Set-Location "c:\Users\manam\Desktop\4360 cs Senior Experience\Hardware-Genie"
$overridesPath = Join-Path $PWD "run_task_seed_once.json"
@'
{
  "containerOverrides": [
    {
      "name": "hardware-genie",
      "environment": [
        { "name": "SEED_SQLITE_TO_RDS", "value": "true" },
        { "name": "SQLITE_SEED_PATH", "value": "/app/instance/parts.db" }
      ]
    }
  ]
}
'@ | Set-Content -Path $overridesPath -Encoding ASCII
```

### 2) Run seed task and wait for completion

```powershell
$taskDefArn = aws ecs describe-services --cluster hardware-genie-cluster --services hardware-genie-service --region us-west-1 --query "services[0].taskDefinition" --output text
$taskArn = aws ecs run-task --cluster hardware-genie-cluster --task-definition $taskDefArn --launch-type FARGATE --network-configuration "awsvpcConfiguration={subnets=[subnet-04cad02ae9164602a,subnet-0e05085f001f8f9e1],securityGroups=[sg-013d93e362ce77dba],assignPublicIp=DISABLED}" --overrides file://$overridesPath --region us-west-1 --query "tasks[0].taskArn" --output text
$taskArn
aws ecs wait tasks-stopped --cluster hardware-genie-cluster --tasks $taskArn --region us-west-1
aws ecs describe-tasks --cluster hardware-genie-cluster --tasks $taskArn --region us-west-1 --query "tasks[0].{last:lastStatus,exit:containers[0].exitCode,stoppedReason:stoppedReason}"
```

### 3) Check seed logs

```powershell
$taskId = ($taskArn -split '/')[-1]
aws logs get-log-events --log-group-name "/ecs/hardware-genie" --log-stream-name "ecs/hardware-genie/$taskId" --region us-west-1 --limit 5000 --query "events[*].message" --output text
```

### 4) Cleanup override file

```powershell
Remove-Item -Path .\run_task_seed_once.json -ErrorAction SilentlyContinue
```

---

## D) Post-Rebuild Validation

Products page check:

```powershell
Invoke-WebRequest "http://$albDns/products?category=video_card" -UseBasicParsing
```

Trends page check:

```powershell
Invoke-WebRequest "http://$albDns/trends" -UseBasicParsing
```

Service health + target health:

```powershell
aws ecs describe-services --cluster hardware-genie-cluster --services hardware-genie-service --region us-west-1 --query "services[0].{running:runningCount,pending:pendingCount,taskDefinition:taskDefinition}"
aws elbv2 describe-target-health --target-group-arn $tgArn --region us-west-1 --query "TargetHealthDescriptions[*].TargetHealth"
```

---

## E) Guardrails To Avoid Previous Issues

- Keep ECS desired count at 1 unless you intentionally scale.
- Do not leave diagnostic one-off tasks running.
- Seed once via one-off task after fresh RDS creation.
- Keep service startup seeding disabled for normal app tasks.
